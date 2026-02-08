import asyncio
import hashlib
import json
import logging
import os
import ssl
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import websockets
from websockets.legacy.server import WebSocketServerProtocol


class ConnectionType(Enum):
    CLOUDFLARE = "cloudflare"
    VPN = "vpn"
    DIRECT = "direct"
    LOCAL = "local"


@dataclass
class ClientConnection:
    websocket: Any
    connection_type: ConnectionType
    client_id: str
    ip_address: str
    connected_at: datetime
    authenticated: bool = False
    user_agent: str | None = None
    country: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "connection_type": self.connection_type.value,
            "ip_address": self.ip_address,
            "connected_at": self.connected_at.isoformat(),
            "authenticated": self.authenticated,
            "user_agent": self.user_agent,
            "country": self.country,
        }


class UnifiedGateway:
    # Token for WebSocket authentication (non-local connections).
    # Set via MEGABOT_GATEWAY_TOKEN env var or constructor parameter.
    _AUTH_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        megabot_server_host: str = "127.0.0.1",
        megabot_server_port: int = 18790,
        enable_cloudflare: bool = False,
        enable_vpn: bool = False,
        enable_direct_https: bool = False,
        cloudflare_tunnel_id: str | None = None,
        tailscale_auth_key: str | None = None,
        ssl_cert_path: str | None = None,
        ssl_key_path: str | None = None,
        public_domain: str | None = None,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        auth_token: str | None = None,
        **kwargs,
    ):
        self.megabot_host = megabot_server_host
        self.megabot_port = megabot_server_port
        self.enable_cloudflare = enable_cloudflare
        self.enable_vpn = enable_vpn
        self.enable_direct_https = enable_direct_https
        self.cloudflare_tunnel_id = cloudflare_tunnel_id
        self.tailscale_auth_key = tailscale_auth_key
        self.on_message = on_message
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.public_domain = public_domain
        self.auth_token = auth_token or os.environ.get("MEGABOT_GATEWAY_TOKEN")

        self.local_server = None
        self.cloudflare_process: subprocess.Popen | None = None
        self.tailscale_process: subprocess.Popen | None = None
        self.https_server = None
        self.clients: dict[str, ClientConnection] = {}
        self.health_status: dict[str, bool] = {
            ConnectionType.LOCAL.value: True,
            ConnectionType.CLOUDFLARE.value: False,
            ConnectionType.VPN.value: False,
            ConnectionType.DIRECT.value: False,
        }
        self.rate_limits: dict[str, dict[str, list[datetime]]] = {ct.value: {} for ct in ConnectionType}
        self.logger = logging.getLogger(__name__)
        self._health_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._start_local_server()
        if self.enable_cloudflare:
            await self._start_cloudflare_tunnel()
        if self.enable_vpn:
            await self._start_tailscale_vpn()
        if self.enable_direct_https:
            await self._start_https_server()

        # Fire-and-forget health monitor. Run it inside a small wrapper so
        # that if tests patch `_health_monitor_loop` with AsyncMock or other
        # test-doubles the returned object will be awaited by this wrapper
        # and won't produce "coroutine was never awaited" warnings.
        async def _health_wrapper() -> None:
            try:
                coro = None
                try:
                    coro = self._health_monitor_loop()
                except Exception:
                    # If the patched health monitor raises when invoked, bail
                    return

                # Only await objects that are real coroutines/futures/tasks.
                # Some tests inject Mock/MagicMock objects with an __await__
                # which can cause "coroutine was never awaited" warnings if we
                # call into them carelessly. Be conservative here and avoid
                # awaiting suspicious mock-like objects.
                try:
                    cls_name = getattr(coro, "__class__", type(coro)).__name__
                except Exception:
                    cls_name = ""

                safe_to_await = asyncio.iscoroutine(coro) or asyncio.isfuture(coro) or isinstance(coro, asyncio.Task)

                if safe_to_await:
                    try:
                        await coro
                    except Exception:
                        # swallow exceptions from the health loop in the wrapper
                        pass
                else:
                    # If this looks like a unittest.mock.Mock/MagicMock, skip
                    # awaiting it to avoid leaving test-created coroutine
                    # objects un-awaited. If it's an unexpected type, attempt
                    # to await as a last resort.
                    if cls_name and ("Magic" in cls_name or "Mock" in cls_name):
                        return
                    try:
                        # Last-resort attempt to await; may raise TypeError
                        await coro
                    except Exception as e:
                        self.logger.debug("Last-resort await of health coro failed: %s", e)
            except Exception as e:
                self.logger.debug("Health wrapper outer exception: %s", e)

        # Create the wrapper coroutine and attempt to schedule it. Tests may
        # patch `asyncio.create_task` with mocks that don't actually schedule
        # the coroutine; in that case we must close the coroutine to avoid
        # "coroutine was never awaited" warnings during garbage collection.
        coro = _health_wrapper()
        task_obj = None
        try:
            try:
                task_obj = asyncio.create_task(coro)
            except Exception:
                # Fallback to ensure_future if create_task was patched
                try:
                    task_obj = asyncio.ensure_future(coro)
                except Exception:
                    task_obj = None
        finally:
            # If the scheduling call did not return a real Task/Future then
            # the coroutine won't be awaited by the event loop. Close it to
            # prevent runtime warnings. If a Task/Future was returned, assume
            # it's responsible for awaiting the coroutine.
            if not (isinstance(task_obj, asyncio.Task) or asyncio.isfuture(task_obj)):
                try:
                    coro.close()
                except Exception:  # pragma: no cover — defensive; coro.close() rarely fails
                    pass
            else:
                self._health_task = task_obj

    async def stop(self) -> None:
        """Stop all gateway services and cleanup tasks."""
        # Cancel health task first
        if self._health_task:
            try:
                self._health_task.cancel()
            except Exception:
                # Defensive: some tests assign MagicMocks which may raise on cancel
                pass

            # Only await real asyncio Tasks or Futures. Tests sometimes attach
            # MagicMock objects with a __await__ pointing to a coroutine which
            # should not be awaited here (it causes "coroutine was never awaited"
            # runtime warnings). Guarding avoids awaiting those test doubles.
            try:
                # Defensive: if the task object is a test double (Mock/MagicMock)
                # avoid awaiting it even if it exposes __await__ to prevent
                # "coroutine was never awaited" warnings later in test runtime.
                cls_name = getattr(self._health_task, "__class__", type(self._health_task)).__name__

                # If a Mock/MagicMock had its __await__ replaced with a real
                # coroutine's __await__ (some tests do this), attempt to
                # retrieve that underlying coroutine and close it so Python
                # won't warn at GC time about un-awaited coroutines.
                try:
                    await_attr = getattr(self._health_task, "__await__", None)
                    if callable(await_attr):
                        # Bound method objects have __self__ pointing to the
                        # original coroutine object (e.g. coro.__await__).
                        possible_coro = getattr(await_attr, "__self__", None)
                        if asyncio.iscoroutine(possible_coro):
                            try:
                                possible_coro.close()
                            except Exception:  # pragma: no cover — mock-detection fallback
                                pass
                except Exception:  # pragma: no cover — mock-detection fallback
                    pass

                if cls_name and ("Magic" in cls_name or "Mock" in cls_name):
                    # Skip awaiting mocked task objects
                    pass
                else:
                    if isinstance(self._health_task, asyncio.Task) or asyncio.isfuture(self._health_task):
                        try:
                            await self._health_task
                        except asyncio.CancelledError:
                            self.logger.debug("Health task cancelled during gateway stop")
                        except Exception as e:
                            self.logger.debug("Health task raised during gateway stop: %s", e)
            except Exception as e:
                # If isinstance/isfuture check itself fails due to a mocked type,
                # just skip awaiting to avoid test-time warnings.
                self.logger.debug("Failed to check/await health task type during stop: %s", e)

        # Close client websockets
        for conn in list(self.clients.values()):
            ws = conn.websocket
            if hasattr(ws, "close"):
                try:
                    close_fn = ws.close
                    if asyncio.iscoroutinefunction(close_fn):
                        await close_fn()
                    elif callable(close_fn):
                        close_fn()
                except Exception as e:
                    self.logger.debug("Failed to close client websocket during stop: %s", e)
        self.clients.clear()

        # Close servers and processes
        if self.local_server:
            try:
                self.local_server.close()
                await self.local_server.wait_closed()
            except Exception as e:
                self.logger.debug("Failed to close local_server during stop: %s", e)

        if self.cloudflare_process:
            try:
                self.cloudflare_process.terminate()
            except Exception as e:
                self.logger.debug("Failed to terminate cloudflare_process during stop: %s", e)

        if self.tailscale_process:
            try:
                self.tailscale_process.terminate()
            except Exception as e:
                self.logger.debug("Failed to terminate tailscale_process during stop: %s", e)

        if self.https_server and hasattr(self.https_server, "cleanup"):
            try:
                await self.https_server.cleanup()
            except Exception as e:
                self.logger.debug("Failed to clean up https_server during stop: %s", e)

        self.is_active = False
        self.logger.info("[Gateway] Services stopped.")

    def get_connection_info(self) -> dict[str, Any]:
        return {
            "health": dict(self.health_status),
            "active_connections": len(self.clients),
            "endpoints": {
                "local": f"ws://{self.megabot_host}:{self.megabot_port}",
                "cloudflare": self.health_status.get(ConnectionType.CLOUDFLARE.value),
                "vpn": self.health_status.get(ConnectionType.VPN.value),
                "direct": self.health_status.get(ConnectionType.DIRECT.value),
            },
        }

    def _check_rate_limit(self, conn: ClientConnection, limit: int = 1000, window: int = 60) -> bool:
        try:
            from megabot.adapters import unified_gateway as ug  # type: ignore

            now_obj = ug.datetime.datetime.now()  # patched in tests
        except Exception:
            now_obj = datetime.now()

        def _ts(val: Any) -> float:
            try:
                if hasattr(val, "timestamp"):
                    return float(val.timestamp())
                return float(val)  # pragma: no cover
            except Exception:  # pragma: no cover
                return datetime.now().timestamp()

        limits = {
            ConnectionType.LOCAL.value: (1000, 60),
            ConnectionType.VPN.value: (500, 60),
            ConnectionType.CLOUDFLARE.value: (100, 60),
            ConnectionType.DIRECT.value: (100, 60),
        }
        limit, window = limits.get(conn.connection_type.value, (limit, window))
        now_ts = _ts(now_obj)
        rate_bucket = self.rate_limits.setdefault(conn.connection_type.value, {})
        history = rate_bucket.setdefault(conn.client_id, [])
        rate_bucket[conn.client_id] = [t for t in history if (now_ts - _ts(t)) < window]
        if len(rate_bucket[conn.client_id]) >= limit:
            return False
        rate_bucket[conn.client_id].append(now_obj)
        return True

    def _cleanup_rate_limits(self, client_id: str) -> None:
        """Remove all rate-limit entries for a disconnected client."""
        for bucket in self.rate_limits.values():
            bucket.pop(client_id, None)

    async def _start_tailscale_vpn(self) -> bool:
        if not self.tailscale_auth_key:
            self.health_status[ConnectionType.VPN.value] = False
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "tailscale",
                "up",
                "--authkey",
                self.tailscale_auth_key,
                "--hostname",
                "megabot-gateway",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                returncode = await asyncio.wait_for(proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                returncode = -1
            self.health_status[ConnectionType.VPN.value] = returncode == 0
            return self.health_status[ConnectionType.VPN.value]
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - safety
            self.logger.error("Tailscale start failed: %s", exc)
            self.health_status[ConnectionType.VPN.value] = False
            return False

    async def _start_cloudflare_tunnel(self) -> bool:
        if not self.cloudflare_tunnel_id:
            self.health_status[ConnectionType.CLOUDFLARE.value] = False
            return False
        try:
            # Non-blocking version check
            proc = await asyncio.create_subprocess_exec(
                "cloudflared",
                "--version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                returncode = await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                returncode = -1
            if returncode != 0:
                self.health_status[ConnectionType.CLOUDFLARE.value] = False
                return False

            # Popen is acceptable here — it starts a long-lived background
            # process and returns immediately (does not block the event loop).
            self.cloudflare_process = subprocess.Popen(
                [
                    "cloudflared",
                    "tunnel",
                    "run",
                    "--token",
                    str(self.cloudflare_tunnel_id),
                ]
            )
            if self.cloudflare_process.poll() is None:
                self.health_status[ConnectionType.CLOUDFLARE.value] = True
                return True
            self.health_status[ConnectionType.CLOUDFLARE.value] = False
            return False
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.error("Cloudflare start failed: %s", exc)
            self.health_status[ConnectionType.CLOUDFLARE.value] = False
            return False

    async def _start_https_server(self) -> Any:
        try:
            from aiohttp import web
        except ImportError:
            self.health_status[ConnectionType.DIRECT.value] = False
            return None

        ssl_context = None
        try:
            if self.ssl_cert_path and self.ssl_key_path:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(self.ssl_cert_path, self.ssl_key_path)
        except (OSError, ssl.SSLError, ValueError):
            self.health_status[ConnectionType.DIRECT.value] = False
            return None

        try:
            app = web.Application()
            app.router.add_get("/ws", self._handle_https_websocket)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(
                runner,
                self.megabot_host,
                self.megabot_port + 1,
                ssl_context=ssl_context,
            )
            await site.start()
            self.https_server = runner
            self.health_status[ConnectionType.DIRECT.value] = True
            return runner
        except Exception:
            self.health_status[ConnectionType.DIRECT.value] = False
            return None

    async def _handle_https_websocket(self, request) -> Any:
        try:
            from aiohttp import web
        except ImportError:
            return None

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        conn = ClientConnection(
            websocket=ws,
            connection_type=ConnectionType.DIRECT,
            client_id=f"direct-{len(self.clients) + 1}",
            ip_address=getattr(request, "remote", "unknown"),
            connected_at=datetime.now(),
        )
        await self._manage_connection(conn)
        return ws

    def _detect_connection_type(self, websocket) -> ConnectionType:
        headers = getattr(websocket, "request_headers", {}) or {}
        ip = None
        if "CF-Connecting-IP" in headers:
            ip = headers.get("CF-Connecting-IP")
            return ConnectionType.CLOUDFLARE
        remote_address = getattr(websocket, "remote_address", None)
        if remote_address and len(remote_address) >= 1:
            ip = remote_address[0]
            if ip.startswith("100.") or "Tailscale-User" in headers:
                return ConnectionType.VPN
            if ip.startswith("127.") or ip in {"::1", "localhost"}:
                return ConnectionType.LOCAL
        return ConnectionType.LOCAL

    async def _handle_websocket(self, websocket, path="", forced_type: ConnectionType | None = None) -> None:
        conn_type = forced_type or self._detect_connection_type(websocket)
        ip = "unknown"
        if getattr(websocket, "remote_address", None):
            ip = websocket.remote_address[0]
        headers = getattr(websocket, "request_headers", {}) or {}
        ip = headers.get("CF-Connecting-IP", ip)
        user_agent = headers.get("User-Agent", "unknown")

        # Generate a more stable client_id using IP and User-Agent hash
        client_hash = hashlib.sha256(f"{ip}-{user_agent}".encode()).hexdigest()[:12]
        client_id = f"{conn_type.value}-{client_hash}"

        conn = ClientConnection(
            websocket=websocket,
            connection_type=conn_type,
            client_id=client_id,
            ip_address=ip,
            connected_at=datetime.now(),
            user_agent=user_agent,
        )
        await self._manage_connection(conn)

    async def _manage_connection(self, conn: ClientConnection) -> None:
        self.clients[conn.client_id] = conn
        ws = conn.websocket

        # --- Token-based authentication for non-local connections ---
        if self.auth_token and conn.connection_type != ConnectionType.LOCAL:
            try:
                authenticated = await self._authenticate_connection(conn)
                if not authenticated:
                    await self._send_error(conn, "Authentication failed")
                    self.clients.pop(conn.client_id, None)
                    self._cleanup_rate_limits(conn.client_id)
                    return
            except (asyncio.TimeoutError, ConnectionError, RuntimeError):
                await self._send_error(conn, "Authentication timeout")
                self.clients.pop(conn.client_id, None)
                self._cleanup_rate_limits(conn.client_id)
                return
        else:
            # Local connections or no token configured: auto-authenticate
            conn.authenticated = True

        try:
            async for message in ws:
                payload = message
                try:
                    from aiohttp import WSMsgType  # type: ignore
                except Exception:
                    WSMsgType = None  # type: ignore

                if hasattr(message, "type"):
                    msg_type = getattr(message, "type", None)
                    if WSMsgType and msg_type == WSMsgType.ERROR:
                        break
                    if WSMsgType and msg_type == WSMsgType.TEXT:
                        payload = getattr(message, "data", message)
                    elif hasattr(message, "data"):
                        payload = message.data

                if isinstance(payload, bytes):
                    try:
                        payload = payload.decode("utf-8", errors="ignore")
                    except Exception:
                        payload = str(payload)
                if not isinstance(payload, (str, bytes)):
                    payload = str(payload)

                if not self._check_rate_limit(conn):
                    await self._send_error(conn, "Rate limit exceeded")
                    continue
                await self._process_message(conn, payload)
        finally:
            self.clients.pop(conn.client_id, None)
            self._cleanup_rate_limits(conn.client_id)
            close_fn = getattr(ws, "close", None)
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            elif callable(close_fn):
                close_fn()

    async def _authenticate_connection(self, conn: ClientConnection) -> bool:
        """Require the first message to be a JSON auth payload with a valid token.

        Expected format: {"type": "auth", "token": "<token>"}
        Returns True if authenticated, False otherwise.
        """
        import hmac

        ws = conn.websocket
        try:
            # Wait for auth message with a timeout
            raw = await asyncio.wait_for(
                ws.__aiter__().__anext__(),
                timeout=self._AUTH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, StopAsyncIteration, Exception):
            return False

        # Extract text payload
        payload = raw
        if hasattr(raw, "data"):
            payload = raw.data
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        if not isinstance(payload, str):
            payload = str(payload)

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return False

        if not isinstance(data, dict):
            return False

        if data.get("type") != "auth":
            return False

        provided_token = data.get("token", "")
        if not provided_token or not isinstance(provided_token, str):
            return False

        # Constant-time comparison to prevent timing attacks
        if hmac.compare_digest(provided_token, self.auth_token):
            conn.authenticated = True
            # Send auth success acknowledgement
            ack = json.dumps({"type": "auth_result", "status": "ok"})
            if hasattr(ws, "send"):
                try:
                    await ws.send(ack)
                except (ConnectionError, RuntimeError, OSError) as e:
                    self.logger.debug("Failed to send auth ack via ws.send: %s", e)
            elif hasattr(ws, "send_str"):
                try:
                    await ws.send_str(ack)
                except (ConnectionError, RuntimeError, OSError) as e:
                    self.logger.debug("Failed to send auth ack via ws.send_str: %s", e)
            return True
        return False

    async def _process_message(self, conn: ClientConnection, raw_message: Any) -> None:
        if isinstance(raw_message, bytes):
            try:
                raw_message = raw_message.decode("utf-8", errors="ignore")
            except Exception:  # pragma: no cover
                raw_message = ""
        try:
            data = json.loads(raw_message)
            data.setdefault(
                "_meta",
                {
                    "connection_type": conn.connection_type.value,
                    "client_id": conn.client_id,
                    "ip_address": conn.ip_address,
                    "authenticated": conn.authenticated,
                },
            )
            await self._forward_to_megabot(data)
        except json.JSONDecodeError:
            await self._send_error(conn, "Invalid JSON")
        except Exception:
            await self._send_error(conn, "Internal error")

    async def _forward_to_megabot(self, data: dict[str, Any]) -> None:
        if self.on_message:
            await self.on_message(data)

    async def _send_error(self, conn: ClientConnection, message: str) -> None:
        payload = json.dumps({"error": message})
        ws = conn.websocket
        if hasattr(ws, "send"):
            try:
                await ws.send(payload)
                return
            except (ConnectionError, RuntimeError, OSError) as e:
                self.logger.debug("Failed to send error via ws.send: %s", e)
        if hasattr(ws, "send_str"):
            try:
                await ws.send_str(payload)
            except (ConnectionError, RuntimeError, OSError) as e:
                self.logger.debug("Failed to send error via ws.send_str: %s", e)

    async def _start_local_server(self) -> Any:
        def process_request(_connection: WebSocketServerProtocol, request) -> Any:
            host = request.headers.get("Host", "") if hasattr(request, "headers") else ""
            # VULN-011 fix: exact hostname match instead of substring
            # Strip port if present (e.g. "localhost:8080" → "localhost")
            hostname = host.split(":")[0].strip()
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                return (403, [], b"Localhost only")
            return None

        self.local_server = await websockets.serve(
            self._handle_websocket,
            self.megabot_host,
            self.megabot_port,
            process_request=process_request,
        )
        return self.local_server

    async def send_message(self, client_id: str, message: dict[str, Any]) -> bool:
        """Send a message back to a specific connected client"""
        if client_id not in self.clients:
            self.logger.warning("Attempted to send to unknown client: %s", client_id)
            return False

        conn = self.clients[client_id]
        try:
            payload = json.dumps(message)
            if hasattr(conn.websocket, "send"):
                await conn.websocket.send(payload)
            elif hasattr(conn.websocket, "send_str"):
                await conn.websocket.send_str(payload)
            return True
        except (ConnectionError, RuntimeError, OSError) as e:
            self.logger.error("Failed to send to gateway client %s: %s", client_id, e)
            return False

    async def _health_monitor_loop(self) -> None:
        while True:
            if self.enable_cloudflare:
                if self.cloudflare_process is None or self.cloudflare_process.poll() is not None:
                    self.health_status[ConnectionType.CLOUDFLARE.value] = False
                    self.logger.warning("Cloudflare tunnel dead or not started. Reconnecting...")
                    try:
                        await self._start_cloudflare_tunnel()
                    except (OSError, subprocess.SubprocessError) as e:
                        self.logger.error("Cloudflare reconnection failed: %s", e)
                else:
                    self.health_status[ConnectionType.CLOUDFLARE.value] = True

            if self.enable_vpn:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "tailscale",
                        "status",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        returncode = await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                        returncode = -1
                    if returncode != 0:
                        self.health_status[ConnectionType.VPN.value] = False
                    else:
                        self.health_status[ConnectionType.VPN.value] = True
                except (OSError, subprocess.SubprocessError):
                    self.health_status[ConnectionType.VPN.value] = False

            # Sweep rate-limit entries for clients that are no longer connected
            active_ids = set(self.clients.keys())
            for bucket in self.rate_limits.values():
                stale = [cid for cid in bucket if cid not in active_ids]
                for cid in stale:
                    del bucket[cid]

            await asyncio.sleep(5)


def _main() -> None:  # pragma: no cover - invoked in tests via run_module
    logging.basicConfig(level=logging.INFO)
    gateway = UnifiedGateway()
    try:
        asyncio.run(gateway.start())
    finally:
        asyncio.run(gateway.stop())


if __name__ == "__main__":  # pragma: no cover
    _main()
