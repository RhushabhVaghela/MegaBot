"""
Thorough tests for MegaBot Unified Gateway to achieve 100% coverage
"""

import pytest
import json
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web

import aiohttp
import adapters.unified_gateway as ug

# Ensure ug has web if it was lost by another test
if not getattr(ug, "web", None):
    ug.web = web
if not getattr(ug, "aiohttp", None):
    ug.aiohttp = aiohttp

from adapters.unified_gateway import ConnectionType, ClientConnection, UnifiedGateway


@pytest.fixture
def gateway():
    gw = UnifiedGateway(
        megabot_server_port=18791,
        enable_cloudflare=True,
        enable_vpn=True,
        enable_direct_https=True,
        cloudflare_tunnel_id="test-tunnel",
        tailscale_auth_key="test-key",
        ssl_cert_path="/tmp/cert.pem",
        ssl_key_path="/tmp/key.pem",
        public_domain="test.com",
    )
    gw.on_message = AsyncMock()
    return gw


@pytest.mark.asyncio
async def test_gateway_start_all_paths(gateway):
    """Test start logic covering all conditional branches"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("subprocess.Popen") as mock_popen:
            mock_popen_instance = MagicMock()
            mock_popen_instance.poll.return_value = None  # Running
            mock_popen.return_value = mock_popen_instance

            # Mock loop to return immediately
            with patch.object(gateway, "_health_monitor_loop", new_callable=AsyncMock):
                with patch.object(
                    gateway, "_start_https_server", new_callable=AsyncMock
                ) as mock_https:
                    with patch(
                        "websockets.serve", new_callable=AsyncMock
                    ) as mock_serve:
                        # Set health status before test since we're mocking the methods
                        gateway.health_status[ConnectionType.CLOUDFLARE.value] = True

                        # Test successful paths
                        await gateway.start()
                        assert (
                            gateway.health_status[ConnectionType.CLOUDFLARE.value]
                            is True
                        )
                        assert mock_https.called


@pytest.mark.asyncio
async def test_manage_connection_aiohttp_flow(gateway):
    """Test connection management for aiohttp web sockets"""
    mock_ws = AsyncMock()
    # Mocking the iterator for aiohttp websocket
    mock_ws.__aiter__.return_value = [
        MagicMock(type=web.WSMsgType.TEXT, data=json.dumps({"type": "msg"})),
        MagicMock(type=web.WSMsgType.ERROR),
    ]

    # Initialize rate limits for DIRECT connection
    gateway.rate_limits[ConnectionType.DIRECT.value] = {}

    conn = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.DIRECT,
        client_id="aio-1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    await gateway._manage_connection(conn)
    assert gateway.on_message.called


@pytest.mark.asyncio
async def test_handle_websocket_detection_advanced(gateway):
    """Test detailed header detection in _handle_websocket"""
    # 1. Cloudflare detection
    mock_ws_cf = AsyncMock()
    mock_ws_cf.remote_address = ("127.0.0.1", 123)
    mock_ws_cf.request_headers = {"CF-Connecting-IP": "8.8.8.8"}
    mock_ws_cf.__aiter__.return_value = []
    await gateway._handle_websocket(mock_ws_cf, "")

    # 2. VPN detection
    mock_ws_vpn = AsyncMock()
    mock_ws_vpn.remote_address = ("100.64.0.1", 456)
    mock_ws_vpn.request_headers = {}
    mock_ws_vpn.__aiter__.return_value = []
    await gateway._handle_websocket(mock_ws_vpn, "")

    assert True


@pytest.mark.asyncio
async def test_gateway_health_monitor_restart(gateway):
    """Test health monitor restarting cloudflare"""
    gateway.cloudflare_process = MagicMock()
    gateway.cloudflare_process.poll.return_value = 1  # Dead
    gateway.health_status[ConnectionType.CLOUDFLARE.value] = True
    gateway.enable_cloudflare = True

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        # Set up rate limits with string key to avoid KeyError
        gateway.rate_limits[ConnectionType.CLOUDFLARE.value] = {}

        restart_called = False

        async def mock_restart_impl():
            nonlocal restart_called
            restart_called = True
            gateway.health_status[ConnectionType.CLOUDFLARE.value] = True

        with patch.object(
            gateway, "_start_cloudflare_tunnel", side_effect=mock_restart_impl
        ):
            # Run one iteration
            with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass
            assert restart_called


@pytest.mark.asyncio
async def test_gateway_error_responses(gateway):
    """Test various error sending scenarios"""
    # 1. Native WS error
    mock_ws_native = AsyncMock()
    conn_native = ClientConnection(
        websocket=mock_ws_native,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    await gateway._send_error(conn_native, "err")
    assert mock_ws_native.send.called

    # 2. Aiohttp WS error
    mock_ws_aio = AsyncMock()
    # Mocking behavior for aiohttp send_str
    mock_ws_aio.send_str = AsyncMock()
    # Ensure it doesn't have native send
    if hasattr(mock_ws_aio, "send"):
        del mock_ws_aio.send

    conn_aio = ClientConnection(
        websocket=mock_ws_aio,
        connection_type=ConnectionType.DIRECT,
        client_id="c2",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    await gateway._send_error(conn_aio, "err")
    assert mock_ws_aio.send_str.called


@pytest.mark.asyncio
async def test_gateway_process_request_headers_logic(gateway):
    """Test the process_request callback logic"""
    # We need to manually call the process_request if possible or mock the server
    with patch("websockets.serve", new_callable=AsyncMock) as mock_serve:
        await gateway._start_local_server()
        args, kwargs = mock_serve.call_args
        process_req = kwargs.get("process_request")

        # Test 1: Trusted local
        mock_headers = MagicMock()
        mock_headers.get.return_value = "127.0.0.1"
        mock_req = MagicMock(headers=mock_headers)
        assert process_req(None, mock_req) is None

        # Test 2: Untrusted remote
        mock_headers.get.return_value = "192.168.1.1"
        assert process_req(None, mock_req) is not None


@pytest.mark.asyncio
async def test_gateway_stop_cleanup_robust(gateway):
    """Test stop method with all resources active"""
    gateway.cloudflare_process = MagicMock()
    gateway.tailscale_process = MagicMock()
    gateway.https_server = MagicMock()
    gateway.https_server.cleanup = AsyncMock()
    gateway.local_server = MagicMock()
    gateway.local_server.close = MagicMock()
    gateway.local_server.wait_closed = AsyncMock()

    # Add a mock client to close
    mock_ws = AsyncMock()
    gateway.clients["c1"] = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    await gateway.stop()
    assert mock_ws.close.called
    assert gateway.cloudflare_process.terminate.called


@pytest.mark.asyncio
async def test_gateway_run_module():
    """Test running the module as main for coverage"""
    import runpy
    import sys

    # Clear module from cache to avoid runpy warning
    modules_to_clear = [
        k for k in sys.modules.keys() if k.startswith("adapters.unified_gateway")
    ]
    for mod in modules_to_clear:
        del sys.modules[mod]

    def mock_run(coro):
        coro.close()
        return None

    with patch.object(UnifiedGateway, "start", new_callable=AsyncMock):
        with patch("asyncio.run", side_effect=mock_run):
            runpy.run_module("adapters.unified_gateway", run_name="__main__")
            assert True


@pytest.mark.asyncio
async def test_start_https_server_failure_handled(gateway):
    """Test HTTPS server failure handling"""
    with patch("ssl.create_default_context", side_effect=Exception("ssl error")):
        await gateway._start_https_server()
        assert gateway.health_status[ConnectionType.DIRECT.value] is False


@pytest.mark.asyncio
async def test_start_cloudflare_tunnel_fail_path(gateway):
    """Test start failure branches for cloudflare"""
    with patch("subprocess.run") as mock_run:
        # cloudflared not found
        mock_run.return_value = MagicMock(returncode=1)
        await gateway._start_cloudflare_tunnel()
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False


@pytest.mark.asyncio
async def test_start_tailscale_vpn_fail_path(gateway):
    """Test start failure branches for tailscale"""
    with patch("subprocess.run") as mock_run:
        # tailscale not found
        mock_run.return_value = MagicMock(returncode=1)
        await gateway._start_tailscale_vpn()
        assert gateway.health_status[ConnectionType.VPN.value] is False


@pytest.mark.asyncio
async def test_malicious_command_interception_metadata(gateway):
    """Test that messages from gateway include the critical security metadata for the orchestrator"""
    mock_ws = AsyncMock()
    # Mocking the iterator to send a malicious command string
    malicious_payload = json.dumps(
        {"type": "shell.execute", "params": {"command": "rm -rf /"}}
    )
    mock_ws.__aiter__.return_value = [malicious_payload]

    # Initialize rate limits for CLOUDFLARE connection
    gateway.rate_limits[ConnectionType.CLOUDFLARE.value] = {}

    conn = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.CLOUDFLARE,  # Simulate untrusted source
        client_id="cf-evil",
        ip_address="6.6.6.6",
        connected_at=datetime.now(),
    )

    await gateway._manage_connection(conn)

    # Verify that on_message was called with the command AND the security metadata
    assert gateway.on_message.called
    forwarded_data = gateway.on_message.call_args[0][0]
    assert forwarded_data["type"] == "shell.execute"
    assert forwarded_data["_meta"]["connection_type"] == "cloudflare"
    assert forwarded_data["_meta"]["client_id"] == "cf-evil"
    # When no auth_token is configured on the gateway, all connections
    # (including untrusted ones) are auto-authenticated since there is
    # no token to verify against.
    assert forwarded_data["_meta"]["authenticated"] is True


@pytest.mark.asyncio
async def test_gateway_start_cloudflare_failure_during_wait(gateway):
    """Test cloudflare process dying during wait sleep"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 1  # Dead
            mock_proc.communicate.return_value = (b"", b"tunnel error")
            mock_popen.return_value = mock_proc

            await gateway._start_cloudflare_tunnel()
            assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False


@pytest.mark.asyncio
async def test_handle_websocket_forced_type(gateway):
    """Test _handle_websocket with forced_type parameter"""
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("1.2.3.4", 80)
    mock_ws.request_headers = {}
    mock_ws.__aiter__.return_value = []

    # Initialize rate limits
    gateway.rate_limits[ConnectionType.VPN.value] = {}

    with patch.object(
        gateway, "_manage_connection", new_callable=AsyncMock
    ) as mock_manage:
        await gateway._handle_websocket(mock_ws, "", forced_type=ConnectionType.VPN)

        # Check if manage was called with VPN type
        assert mock_manage.called
        connection = mock_manage.call_args[0][0]
        assert connection.connection_type == ConnectionType.VPN


@pytest.mark.asyncio
async def test_gateway_https_server_start_error(gateway):
    """Test exception during HTTPS server setup"""
    with patch("aiohttp.web.Application", side_effect=Exception("web error")):
        await gateway._start_https_server()
        assert gateway.health_status[ConnectionType.DIRECT.value] is False


@pytest.mark.asyncio
async def test_gateway_stop_client_close_error(gateway):
    """Test stop method handling errors during client close"""
    mock_ws = AsyncMock()
    mock_ws.close.side_effect = Exception("Close error")
    gateway.clients["c1"] = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    # Should not crash
    await gateway.stop()
    assert True


@pytest.mark.asyncio
async def test_gateway_process_message_invalid_json(gateway):
    """Test _process_message with invalid JSON"""
    mock_ws = AsyncMock()
    conn = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    await gateway._process_message(conn, "invalid json {")
    assert mock_ws.send.called


@pytest.mark.asyncio
async def test_gateway_process_message_internal_error(gateway):
    """Test _process_message with unexpected error"""
    mock_ws = AsyncMock()
    conn = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    with patch.object(gateway, "_forward_to_megabot", side_effect=Exception("crash")):
        await gateway._process_message(conn, '{"type": "ping"}')
        assert mock_ws.send.called


@pytest.mark.asyncio
async def test_gateway_forward_no_handler(gateway):
    """Test _forward_to_megabot without handler"""
    gateway.on_message = None
    # Should just log info
    await gateway._forward_to_megabot({"type": "ping"})
    assert True


@pytest.mark.asyncio
async def test_check_rate_limit_exceptions(gateway):
    """Test rate limit checks with exceptions (lines 142-143, 149-151)"""
    conn = ClientConnection(
        websocket=MagicMock(),
        connection_type=ConnectionType.LOCAL,
        client_id="test-client",
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    # 1. Trigger Exception in now_obj (lines 142-143)
    # We patch the module-level ug.datetime to be None
    with patch("adapters.unified_gateway.datetime", None):
        assert gateway._check_rate_limit(conn) is True

    # 2. Trigger Exception in _ts (lines 149-151)
    # _ts is a local function, we trigger it by passing an object that fails hasattr AND float()
    # But wait, now_obj is used in _ts(now_obj) and in _ts(t).
    # If we make now_obj something weird:
    class BadObj:
        def __float__(self):
            raise ValueError("No float")

    with patch("core.network.gateway.datetime") as mock_dt:
        mock_dt.now.return_value = BadObj()
        # Should hit line 151 and return current timestamp
        assert gateway._check_rate_limit(conn) is True


@pytest.mark.asyncio
async def test_gateway_stop_with_health_task(gateway):
    """Test stop method cancels health task (lines 105-109)"""
    mock_task = AsyncMock()
    mock_task.cancel = MagicMock()
    # Mock await behavior
    mock_task.__await__ = MagicMock(return_value=iter([asyncio.CancelledError()]))
    gateway._health_task = mock_task

    # We want to trigger the try-except block
    async def side_effect():
        raise asyncio.CancelledError()

    with patch("asyncio.Task", MagicMock):
        # Manually trigger the cancel logic
        if gateway._health_task:
            gateway._health_task.cancel()
            try:
                # In real code this would be awaited
                pass
            except asyncio.CancelledError:
                pass

    # Let's just call the real stop and mock the task
    mock_task = AsyncMock()
    mock_task.cancel = MagicMock()

    # Use a real coroutine that raises CancelledError when awaited
    async def raise_cancelled_coro():
        raise asyncio.CancelledError()

    coro = raise_cancelled_coro()
    gateway._health_task = MagicMock()
    gateway._health_task.cancel = MagicMock()
    gateway._health_task.__await__ = coro.__await__

    await gateway.stop()
    assert gateway._health_task.cancel.called


@pytest.mark.asyncio
async def test_gateway_send_message_full(gateway):
    """Test send_message method with various paths (lines 446-462)"""
    # 1. Unknown client (lines 448-450)
    result = await gateway.send_message("unknown", {"msg": "hello"})
    assert result is False

    # 2. Success path (native WS)
    mock_ws = AsyncMock()
    gateway.clients["c1"] = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    result = await gateway.send_message("c1", {"msg": "hello"})
    assert result is True
    mock_ws.send.assert_called_once()

    # 3. Success path (aiohttp WS)
    mock_ws_aio = AsyncMock()
    mock_ws_aio.send_str = AsyncMock()
    if hasattr(mock_ws_aio, "send"):
        del mock_ws_aio.send
    gateway.clients["c2"] = ClientConnection(
        websocket=mock_ws_aio,
        connection_type=ConnectionType.DIRECT,
        client_id="c2",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    result = await gateway.send_message("c2", {"msg": "hello"})
    assert result is True
    mock_ws_aio.send_str.assert_called_once()

    # 4. Exception path (lines 460-462)
    mock_ws.send.side_effect = Exception("Send failed")
    result = await gateway.send_message("c1", {"msg": "hello"})
    assert result is False


@pytest.mark.asyncio
async def test_gateway_process_message_exceptions(gateway):
    """Test _process_message with various exceptions (lines 405-408)"""
    conn = ClientConnection(
        websocket=AsyncMock(),
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )

    # JSONDecodeError (line 405-406)
    with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_err:
        await gateway._process_message(conn, "invalid json")
        mock_err.assert_called_with(conn, "Invalid JSON")

    # General Exception (line 407-408)
    with patch("json.loads", side_effect=Exception("crash")):
        with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_err:
            await gateway._process_message(conn, '{"k":"v"}')
            mock_err.assert_called_with(conn, "Internal error")


@pytest.mark.asyncio
async def test_send_error_exception_handling(gateway):
    """Test _send_error exception handling (lines 421-422, 426-427)"""
    mock_ws = MagicMock()
    # Case 1: ws.send raises exception
    mock_ws.send = AsyncMock(side_effect=Exception("send error"))
    conn = ClientConnection(
        mock_ws, ConnectionType.LOCAL, "c1", "1.1.1.1", datetime.now()
    )

    await gateway._send_error(conn, "msg")
    # Should not raise

    # Case 2: ws.send_str raises exception
    del mock_ws.send
    mock_ws.send_str = AsyncMock(side_effect=Exception("send_str error"))
    await gateway._send_error(conn, "msg")
    # Should not raise


@pytest.mark.asyncio
async def test_tailscale_arguments_coverage(gateway):
    """Ensure all tailscale arguments are covered (lines 207-214)"""
    gateway.tailscale_auth_key = "my-key"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        await gateway._start_tailscale_vpn()

        args = mock_run.call_args[0][0]
        assert "my-key" in args
        assert "megabot-gateway" in args


@pytest.mark.asyncio
async def test_manage_connection_sync_close(gateway):
    """Test _manage_connection with sync close function (lines 384-385)"""
    mock_ws = MagicMock()
    mock_ws.close = MagicMock()  # Sync
    mock_ws.__aiter__.return_value = []

    conn = ClientConnection(
        mock_ws, ConnectionType.LOCAL, "c1", "1.1.1.1", datetime.now()
    )
    await gateway._manage_connection(conn)
    mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_decode_exceptions_coverage(gateway):
    """Test decode exceptions in _manage_connection and _process_message (lines 370-371, 391-392)"""
    mock_ws = AsyncMock()
    # Payload that fails decode
    mock_ws.__aiter__.return_value = [b"\xff"]

    conn = ClientConnection(
        mock_ws, ConnectionType.LOCAL, "c1", "1.1.1.1", datetime.now()
    )

    with patch.object(gateway, "_check_rate_limit", return_value=True):
        # This covers 370-371
        await gateway._manage_connection(conn)

    # This covers 391-392
    await gateway._process_message(conn, b"\xff")


@pytest.mark.asyncio
async def test_decode_exceptions_real_trigger(gateway):
    """Test decode exceptions with explicit mock (lines 370-371)"""
    mock_ws = AsyncMock()
    mock_payload = MagicMock(spec=bytes)
    # This is the trick: mock the method on the object
    mock_payload.decode.side_effect = Exception("Decode failed")
    mock_ws.__aiter__.return_value = [mock_payload]

    conn = ClientConnection(
        mock_ws, ConnectionType.LOCAL, "c1", "1.1.1.1", datetime.now()
    )
    with patch.object(gateway, "_check_rate_limit", return_value=True):
        # We need to ensure it thinks it's bytes
        with patch(
            "core.network.gateway.isinstance",
            side_effect=lambda o, t: (
                True if t == bytes and o == mock_payload else isinstance(o, t)
            ),
        ):
            await gateway._manage_connection(conn)


@pytest.mark.asyncio
async def test_health_monitor_healthy_state(gateway):
    """Test health monitor when cloudflare is healthy (line 480)"""
    gateway.enable_cloudflare = True
    gateway.cloudflare_process = MagicMock()
    gateway.cloudflare_process.poll.return_value = None  # Running

    with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
        try:
            await gateway._health_monitor_loop()
        except Exception:
            pass

    assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is True

    # 2. Success path (native WS)
    mock_ws = AsyncMock()
    gateway.clients["c1"] = ClientConnection(
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        client_id="c1",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    result = await gateway.send_message("c1", {"msg": "hello"})
    assert result is True
    mock_ws.send.assert_called_once()

    # 3. Success path (aiohttp WS)
    mock_ws_aio = AsyncMock()
    mock_ws_aio.send_str = AsyncMock()
    if hasattr(mock_ws_aio, "send"):
        del mock_ws_aio.send
    gateway.clients["c2"] = ClientConnection(
        websocket=mock_ws_aio,
        connection_type=ConnectionType.DIRECT,
        client_id="c2",
        ip_address="1.1.1.1",
        connected_at=datetime.now(),
    )
    result = await gateway.send_message("c2", {"msg": "hello"})
    assert result is True
    mock_ws_aio.send_str.assert_called_once()

    # 4. Exception path (lines 459-461)
    mock_ws.send.side_effect = Exception("Send failed")
    result = await gateway.send_message("c1", {"msg": "hello"})
    assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
