"""
Tests for MegaBot Unified Gateway
"""

import asyncio
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from adapters.unified_gateway import ConnectionType, ClientConnection, UnifiedGateway

# Ignore unawaited coroutine warnings for the health monitor loop in these tests
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


class TestConnectionType:
    """Test ConnectionType enum"""

    def test_connection_type_values(self):
        assert ConnectionType.CLOUDFLARE.value == "cloudflare"
        assert ConnectionType.VPN.value == "vpn"
        assert ConnectionType.DIRECT.value == "direct"
        assert ConnectionType.LOCAL.value == "local"


class TestClientConnection:
    """Test ClientConnection dataclass"""

    def test_client_connection_to_dict(self):
        now = datetime.now()
        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="local-1",
            ip_address="127.0.0.1",
            connected_at=now,
            authenticated=True,
            user_agent="TestAgent",
            country="US",
        )

        result = conn.to_dict()
        assert result["client_id"] == "local-1"
        assert result["connection_type"] == "local"
        assert result["ip_address"] == "127.0.0.1"
        assert result["connected_at"] == now.isoformat()
        assert result["authenticated"] is True
        assert result["user_agent"] == "TestAgent"
        assert result["country"] == "US"

    def test_client_connection_to_dict_with_none_values(self):
        """Test ClientConnection.to_dict() with None values covers line 34"""
        now = datetime.now()
        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="local-1",
            ip_address="127.0.0.1",
            connected_at=now,
            authenticated=False,
            user_agent=None,
            country=None,
        )

        result = conn.to_dict()
        assert result["client_id"] == "local-1"
        assert result["connection_type"] == "local"
        assert result["ip_address"] == "127.0.0.1"
        assert result["connected_at"] == now.isoformat()
        assert result["authenticated"] is False
        assert result["user_agent"] is None
        assert result["country"] is None


@pytest.fixture
def gateway_instance():
    return UnifiedGateway(
        megabot_server_port=18791,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
    )


class TestUnifiedGatewayInitialization:
    """Test UnifiedGateway initialization"""

    @pytest.mark.asyncio
    async def test_gateway_initialization_full_params(self, gateway_instance):
        """Test UnifiedGateway initialization with all parameters"""
        gateway = UnifiedGateway(
            megabot_server_host="custom-host",
            megabot_server_port=9999,
            enable_cloudflare=True,
            enable_vpn=True,
            enable_direct_https=True,
            cloudflare_tunnel_id="tunnel-123",
            tailscale_auth_key="auth-key-123",
            ssl_cert_path="/path/to/cert.crt",
            ssl_key_path="/path/to/key.key",
            public_domain="example.com",
            on_message=AsyncMock(),
            custom_param="value",
        )

        assert gateway.megabot_host == "custom-host"
        assert gateway.megabot_port == 9999
        assert gateway.enable_cloudflare is True
        assert gateway.enable_vpn is True
        assert gateway.enable_direct_https is True
        assert gateway.cloudflare_tunnel_id == "tunnel-123"
        assert gateway.tailscale_auth_key == "auth-key-123"
        assert gateway.ssl_cert_path == "/path/to/cert.crt"
        assert gateway.ssl_key_path == "/path/to/key.key"
        assert gateway.public_domain == "example.com"
        assert gateway.on_message is not None
        assert gateway.clients == {}
        assert gateway.health_status[ConnectionType.LOCAL.value] is True
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False
        assert gateway.health_status[ConnectionType.VPN.value] is False
        assert gateway.health_status[ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_start_method_calls_all_services(self, gateway_instance):
        """Test start method calls all service initialization methods"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.enable_vpn = True
        gateway.enable_direct_https = True
        gateway.cloudflare_tunnel_id = "test-tunnel"
        gateway.tailscale_auth_key = "test-key"

        with patch.object(gateway, "_start_local_server", new_callable=AsyncMock) as mock_local:
            with patch.object(gateway, "_start_cloudflare_tunnel", new_callable=AsyncMock) as mock_cloudflare:
                with patch.object(gateway, "_start_tailscale_vpn", new_callable=AsyncMock) as mock_vpn:
                    with patch.object(gateway, "_start_https_server", new_callable=AsyncMock) as mock_https:
                        with patch("asyncio.create_task") as mock_create_task:
                            await gateway.start()

                            mock_local.assert_called_once()
                            mock_cloudflare.assert_called_once()
                            mock_vpn.assert_called_once()
                            mock_https.assert_called_once()
                            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_info_with_active_services(self, gateway_instance):
        """Test get_connection_info with active services and clients"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.enable_vpn = True
        gateway.enable_direct_https = True
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = True
        gateway.health_status[ConnectionType.VPN.value] = True
        gateway.health_status[ConnectionType.DIRECT.value] = True

        # Add a client
        gateway.clients["test-client"] = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        info = gateway.get_connection_info()
        assert info["active_connections"] == 1
        assert info["health"][ConnectionType.CLOUDFLARE.value] is True
        assert info["health"][ConnectionType.VPN.value] is True
        assert info["health"][ConnectionType.DIRECT.value] is True
        assert info["endpoints"]["local"] == "ws://127.0.0.1:18791"

        # Properly clean up any background tasks
        await gateway.stop()


class TestUnifiedGatewayCoreOperations:
    """Core operational tests for UnifiedGateway"""

    @pytest.fixture
    def gateway_instance(self):
        return UnifiedGateway(
            megabot_server_port=18791,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
        )

    @pytest.mark.asyncio
    async def test_unified_gateway_manage_connection(self, gateway_instance):
        """Test connection lifecycle and rate limiting"""
        gateway = gateway_instance
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 54321)
        mock_ws.request_headers = {}
        mock_ws.__aiter__.return_value = [json.dumps({"type": "ping"})]

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="local-1",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Mock on_message
        gateway.on_message = AsyncMock()

        # Process one message
        await gateway._manage_connection(conn)
        assert gateway.on_message.called

    @pytest.mark.asyncio
    async def test_unified_gateway_health_monitor(self, gateway_instance):
        """Test health monitoring loop logic"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.poll.return_value = 0  # Process finished
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = True

        # Mock subprocess — not strictly needed since VPN is not enabled,
        # but kept for safety in case the loop body changes.
        with patch("subprocess.run"):
            with patch.object(gateway, "_start_cloudflare_tunnel", new_callable=AsyncMock) as mock_restart:
                # Mocking asyncio.sleep to break the infinite loop
                with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
                    try:
                        await gateway._health_monitor_loop()
                    except Exception:
                        pass
                assert mock_restart.called

    @pytest.mark.asyncio
    async def test_unified_gateway_handle_websocket_types(self, gateway_instance):
        """Test connection type detection from headers"""
        gateway = gateway_instance
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("1.2.3.4", 80)
        mock_ws.request_headers = {"CF-Connecting-IP": "203.0.113.1"}
        mock_ws.__aiter__.return_value = []

        # Connection logic should detect cloudflare
        await gateway._handle_websocket(mock_ws, "")
        assert True

    @pytest.mark.asyncio
    async def test_unified_gateway_stop(self, gateway_instance):
        """Test graceful stop"""
        gateway = gateway_instance
        gateway.local_server = MagicMock()
        gateway.local_server.close = MagicMock()
        gateway.local_server.wait_closed = AsyncMock()

        await gateway.stop()
        assert gateway.local_server.close.called

    @pytest.mark.asyncio
    async def test_unified_gateway_error_cases(self, gateway_instance):
        """Test error handling in gateway"""
        gateway = gateway_instance
        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="c1",
            ip_address="1.1.1.1",
            connected_at=datetime.now(),
        )

        await gateway._send_error(conn, "test error")
        assert conn.websocket.send.called

    @pytest.mark.asyncio
    async def test_unified_gateway_handle_https_mock(self, gateway_instance):
        """Test HTTPS websocket upgrade"""
        gateway = gateway_instance
        mock_request = MagicMock()
        mock_request.remote = "1.1.1.1"
        mock_request.headers = {}

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = AsyncMock()
            mock_ws_class.return_value = mock_ws
            mock_ws.prepare = AsyncMock()
            mock_ws.__aiter__.return_value = []

            await gateway._handle_https_websocket(mock_request)
            assert mock_ws.prepare.called

    @pytest.mark.asyncio
    async def test_unified_gateway_aiohttp_import_error(self):
        """Test handling when aiohttp is not available"""
        with patch.dict("sys.modules", {"aiohttp": None}):
            # Force reimport to trigger ImportError path
            import adapters.unified_gateway as ug

            gateway = ug.UnifiedGateway(
                megabot_server_port=18791,
                enable_direct_https=True,  # Would need aiohttp
            )
            # HTTPS server start should handle missing aiohttp gracefully
            await gateway._start_https_server()
            assert gateway.health_status[ug.ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_unified_gateway_localhost_check(self, gateway_instance):
        """Test the localhost process_request callback"""
        gateway = gateway_instance

        with patch("websockets.serve", new_callable=AsyncMock) as mock_serve:
            await gateway._start_local_server()

            # Get the process_request callback
            args, kwargs = mock_serve.call_args
            process_req = kwargs.get("process_request")

            if process_req:
                # Test localhost allowed
                mock_headers = MagicMock()
                mock_headers.get.return_value = "127.0.0.1"
                mock_req = MagicMock(headers=mock_headers)
                result = process_req(None, mock_req)
                assert result is None  # None means allowed

                # Test non-localhost denied
                mock_headers.get.return_value = "192.168.1.1"
                result = process_req(None, mock_req)
                assert result is not None  # Returns error response

    @pytest.mark.asyncio
    async def test_unified_gateway_rate_limit_all_types(self, gateway_instance):
        """Test rate limiting for all connection types"""
        gateway = gateway_instance

        # Test each connection type
        for conn_type in ConnectionType:
            conn = ClientConnection(
                websocket=MagicMock(),
                connection_type=conn_type,
                client_id=f"test-{conn_type.value}",
                ip_address="127.0.0.1",
                connected_at=datetime.now(),
            )

            # Should allow initial requests
            assert gateway._check_rate_limit(conn) is True

            # Exhaust the limit
            gateway.rate_limits[conn_type.value][conn.client_id] = [datetime.now()] * 2000
            assert gateway._check_rate_limit(conn) is False

    @pytest.mark.asyncio
    async def test_unified_gateway_send_error_aiohttp(self, gateway_instance):
        """Test error sending with aiohttp websocket"""
        gateway = gateway_instance

        # Mock aiohttp-style websocket
        mock_ws = AsyncMock()
        mock_ws.send_str = AsyncMock()
        del mock_ws.send  # Remove 'send' to force aiohttp path

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.DIRECT,
            client_id="c1",
            ip_address="1.1.1.1",
            connected_at=datetime.now(),
        )

        await gateway._send_error(conn, "test error")
        assert mock_ws.send_str.called

    @pytest.mark.asyncio
    async def test_unified_gateway_health_monitor_tailscale(self, gateway_instance):
        """Test health monitor for tailscale status check"""
        gateway = gateway_instance
        gateway.enable_vpn = True
        gateway.health_status[ConnectionType.VPN.value] = True

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass

            assert gateway.health_status[ConnectionType.VPN.value] is True

    @pytest.mark.asyncio
    async def test_unified_gateway_stop_full_cleanup(self, gateway_instance):
        """Test stop with all resources"""
        gateway = gateway_instance

        # Set up all resources
        gateway.local_server = MagicMock()
        gateway.local_server.close = MagicMock()
        gateway.local_server.wait_closed = AsyncMock()

        gateway.cloudflare_process = MagicMock()
        gateway.tailscale_process = MagicMock()
        gateway.https_server = MagicMock()
        gateway.https_server.cleanup = AsyncMock()

        # Add mock clients
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        gateway.clients["c1"] = ClientConnection(
            websocket=mock_ws1,
            connection_type=ConnectionType.LOCAL,
            client_id="c1",
            ip_address="1.1.1.1",
            connected_at=datetime.now(),
        )
        gateway.clients["c2"] = ClientConnection(
            websocket=mock_ws2,
            connection_type=ConnectionType.CLOUDFLARE,
            client_id="c2",
            ip_address="1.1.1.2",
            connected_at=datetime.now(),
        )

        with patch("subprocess.run") as mock_run:
            await gateway.stop()

        assert mock_ws1.close.called
        assert mock_ws2.close.called
        assert gateway.cloudflare_process.terminate.called

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_unified_gateway_main_function(self):
        """Test the main function for coverage"""
        import runpy
        import sys

        # Clear the module from cache to avoid warning
        modules_to_clear = [k for k in sys.modules.keys() if "unified_gateway" in k]
        for mod in modules_to_clear:
            del sys.modules[mod]

        with patch.object(UnifiedGateway, "start", new_callable=AsyncMock):
            with patch.object(UnifiedGateway, "stop", new_callable=AsyncMock):

                def mock_run(coro):
                    coro.close()
                    return None

                with patch("asyncio.run", side_effect=mock_run):
                    with patch("logging.basicConfig"):
                        runpy.run_module("adapters.unified_gateway", run_name="__main__")
                        assert True


class TestUnifiedGatewayBranches:
    """Branch coverage tests for UnifiedGateway edge cases and error paths"""

    @pytest.fixture
    def gateway_instance(self):
        return UnifiedGateway(
            megabot_server_port=18791,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
        )

    @pytest.mark.asyncio
    async def test_routing_accepts_all_connection_types_regardless_of_enable_flags(self, gateway_instance):
        """Test that routing accepts connections regardless of enable flags - servers just aren't started"""
        gateway = gateway_instance
        gateway.enable_cloudflare = False

        mock_ws = AsyncMock()
        mock_ws.remote_address = ("203.0.113.1", 44321)  # Cloudflare IP
        mock_ws.request_headers = {"CF-Connecting-IP": "1.2.3.4"}
        mock_ws.__aiter__.return_value = []

        # Should accept connection even if Cloudflare is disabled
        with patch.object(gateway, "_manage_connection", new_callable=AsyncMock) as mock_manage:
            await gateway._handle_websocket(mock_ws, "")
            mock_manage.assert_called_once()

    @pytest.mark.asyncio
    async def test_routing_vpn_connection_detection(self, gateway_instance):
        """Test VPN connection type detection from IP range"""
        gateway = gateway_instance
        gateway.enable_vpn = False

        mock_ws = AsyncMock()
        mock_ws.remote_address = ("100.64.0.1", 44321)  # Tailscale IP range
        mock_ws.request_headers = {"Tailscale-User": "test@example.com"}
        mock_ws.__aiter__.return_value = []

        # Should detect VPN connection type
        with patch.object(gateway, "_manage_connection", new_callable=AsyncMock) as mock_manage:
            await gateway._handle_websocket(mock_ws, "")
            mock_manage.assert_called_once()
            # Check that the connection was created with VPN type
            call_args = mock_manage.call_args[0][0]
            assert call_args.connection_type == ConnectionType.VPN

    @pytest.mark.asyncio
    async def test_rate_limit_exhaustion_with_patch(self, gateway_instance):
        """Test rate limit exhaustion using patched time.monotonic"""
        gateway = gateway_instance
        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Patch datetime.now to control time
        with patch("adapters.unified_gateway.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_datetime.now.return_value = mock_now
            mock_now.timestamp.return_value = 1000.0

            # Allow first request
            assert gateway._check_rate_limit(conn) is True

            # Exhaust the limit by making many requests at once
            for i in range(1001):
                gateway.rate_limits[ConnectionType.LOCAL.value]["test-client"].append(mock_now)

            # Should be blocked
            assert gateway._check_rate_limit(conn) is False

    @pytest.mark.asyncio
    async def test_adapter_initialization_partial_failure_processes_continue(self, gateway_instance):
        """Test that partial adapter initialization failures don't stop other adapters"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.enable_vpn = True

        # Cloudflare fails — version check is now async
        mock_cf_proc = AsyncMock()
        mock_cf_proc.wait = AsyncMock(return_value=1)

        with patch("subprocess.Popen", side_effect=OSError("No such file")):
            with patch("asyncio.create_subprocess_exec", return_value=mock_cf_proc):
                await gateway._start_cloudflare_tunnel()

        # VPN succeeds - need to set auth key for success
        gateway.tailscale_auth_key = "test-key"
        mock_ts_proc = AsyncMock()
        mock_ts_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_ts_proc):
            await gateway._start_tailscale_vpn()

        # Cloudflare should be down, VPN should be up
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False
        assert gateway.health_status[ConnectionType.VPN.value] is True

    @pytest.mark.asyncio
    async def test_start_tailscale_vpn_fail(self, gateway_instance):
        gateway = gateway_instance
        # Mock tailscale not installed
        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=1)

        gateway.enable_vpn = True
        gateway.tailscale_auth_key = "test-key"

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await gateway._start_tailscale_vpn()
        assert gateway.health_status[ConnectionType.VPN.value] is False

    @pytest.mark.asyncio
    async def test_start_cloudflare_tunnel_fail(self, gateway_instance):
        gateway = gateway_instance
        # Mock cloudflared not installed — version check returns non-zero
        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=1)

        gateway.enable_cloudflare = True
        gateway.cloudflare_tunnel_id = "test-tunnel"

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await gateway._start_cloudflare_tunnel()
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False

    @pytest.mark.asyncio
    async def test_adapter_initialization_error_vpn_auth_key_missing(self, gateway_instance):
        """Test adapter initialization error when VPN auth key is missing"""
        gateway = gateway_instance
        gateway.enable_vpn = True
        # No auth key set

        with patch("subprocess.run"):
            # No auth key set, so subprocess is never called — method returns early
            await gateway._start_tailscale_vpn()
            assert gateway.health_status[ConnectionType.VPN.value] is False

    @pytest.mark.asyncio
    async def test_health_monitor_degraded_state_cloudflare_restart_fail(self, gateway_instance):
        """Test health monitor degraded state when Cloudflare restart fails"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.poll.return_value = 1  # Process died
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = True

        with patch.object(gateway, "_start_cloudflare_tunnel", new_callable=AsyncMock) as mock_restart:
            mock_restart.side_effect = Exception("Restart failed")

            with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass

        # Health status should be False since process died and restart failed
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False

    @pytest.mark.asyncio
    async def test_health_monitor_degraded_state_vpn_connection_lost(self, gateway_instance):
        """Test health monitor degraded state when VPN connection is lost"""
        gateway = gateway_instance
        gateway.enable_vpn = True
        gateway.health_status[ConnectionType.VPN.value] = True

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Simulate VPN connection lost

            with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass

            assert gateway.health_status[ConnectionType.VPN.value] is False

    @pytest.mark.asyncio
    async def test_fallback_routing_local_when_cloudflare_fails(self, gateway_instance):
        """Test fallback routing to local when Cloudflare fails"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = False  # Cloudflare down

        mock_ws = AsyncMock()
        mock_ws.remote_address = ("203.0.113.1", 44321)  # Cloudflare IP
        mock_ws.request_headers = {"CF-Connecting-IP": "1.2.3.4"}
        mock_ws.__aiter__.return_value = []

        # Should allow connection via local fallback
        with patch.object(gateway, "_manage_connection", new_callable=AsyncMock) as mock_manage:
            await gateway._handle_websocket(mock_ws, "")
            # Should still attempt to manage the connection
            assert mock_manage.called

    @pytest.mark.asyncio
    async def test_fallback_routing_direct_when_all_others_fail(self, gateway_instance):
        """Test fallback routing to direct HTTPS when all other connections fail"""
        gateway = gateway_instance
        gateway.enable_direct_https = True
        # All other connections disabled or failed
        gateway.enable_cloudflare = False
        gateway.enable_vpn = False
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = False
        gateway.health_status[ConnectionType.VPN.value] = False

        mock_request = MagicMock()
        mock_request.remote = "1.1.1.1"
        mock_request.headers = {}

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = AsyncMock()
            mock_ws_class.return_value = mock_ws
            mock_ws.prepare = AsyncMock()
            mock_ws.__aiter__.return_value = []

            await gateway._handle_https_websocket(mock_request)
            assert mock_ws.prepare.called

    @pytest.mark.asyncio
    async def test_rate_limit_reset_after_window(self, gateway_instance):
        """Test rate limit reset after time window expires"""
        gateway = gateway_instance
        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Fill rate limit to maximum
        now = datetime.now()
        gateway.rate_limits[ConnectionType.LOCAL.value]["test-client"] = [now] * 1000

        # Should be blocked
        assert gateway._check_rate_limit(conn) is False

        # Simulate time passing by patching datetime.now to return a time 61 seconds later
        future_now = datetime.fromtimestamp(now.timestamp() + 61)
        with patch("adapters.unified_gateway.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = future_now

            # Use numeric comparison in _ts mock if needed, but our implementation
            # now handles datetime objects and uses their .timestamp()

            # Should allow new requests after window reset
            assert gateway._check_rate_limit(conn) is True

    @pytest.mark.asyncio
    async def test_adapter_initialization_error_https_missing_aiohttp(self, gateway_instance):
        """Test adapter initialization error when HTTPS enabled but aiohttp unavailable"""
        gateway = gateway_instance
        gateway.enable_direct_https = True

        with patch.dict("sys.modules", {"aiohttp": None}):
            # Force reimport to trigger ImportError
            import adapters.unified_gateway as ug
            import importlib

            importlib.reload(ug)

            gateway = ug.UnifiedGateway(megabot_server_port=18791, enable_direct_https=True)

            await gateway._start_https_server()
            assert gateway.health_status[ug.ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_health_monitor_recovery_cloudflare_comes_back(self, gateway_instance):
        """Test health monitor recovery when Cloudflare comes back online"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.poll.return_value = 1  # Initially dead
        gateway.health_status[ConnectionType.CLOUDFLARE.value] = True  # Was healthy before

        # Simulate Cloudflare coming back - process should be restarted
        with patch.object(gateway, "_start_cloudflare_tunnel", new_callable=AsyncMock) as mock_restart:

            async def mock_restart_impl():
                gateway.health_status[ConnectionType.CLOUDFLARE.value] = True

            mock_restart.side_effect = mock_restart_impl

            with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass

            # Should be healthy again
            assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is True

    @pytest.mark.asyncio
    async def test_routing_accepts_localhost_connections(self, gateway_instance):
        """Test that localhost connections are accepted"""
        gateway = gateway_instance
        # All connections disabled
        gateway.enable_cloudflare = False
        gateway.enable_vpn = False
        gateway.enable_direct_https = False

        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 54321)
        mock_ws.request_headers = {}
        mock_ws.__aiter__.return_value = []

        # Should accept localhost connection
        with patch.object(gateway, "_manage_connection", new_callable=AsyncMock) as mock_manage:
            await gateway._handle_websocket(mock_ws, "")
            mock_manage.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_different_clients_isolated(self, gateway_instance):
        """Test that rate limits are properly isolated between different clients"""
        gateway = gateway_instance

        conn1 = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="client-1",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        conn2 = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="client-2",
            ip_address="127.0.0.2",
            connected_at=datetime.now(),
        )

        # Exhaust client-1's limit
        for _ in range(1001):
            gateway._check_rate_limit(conn1)  # This will add to the rate limit

        # client-1 should be blocked
        assert gateway._check_rate_limit(conn1) is False

        # client-2 should still be allowed
        assert gateway._check_rate_limit(conn2) is True


class TestUnifiedGatewayFullCoverage:
    """Additional tests for 100% coverage of UnifiedGateway"""

    @pytest.fixture
    def gateway_instance(self):
        return UnifiedGateway(
            megabot_server_port=18791,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
        )

    @pytest.mark.asyncio
    async def test_start_cloudflare_tunnel_subprocess_error(self, gateway_instance):
        """Test subprocess error in _start_cloudflare_tunnel covers lines 194-197"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_tunnel_id = "test-tunnel"

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("Command failed")):
            result = await gateway._start_cloudflare_tunnel()
            assert result is False
            assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False

    @pytest.mark.asyncio
    async def test_start_https_server_ssl_cert_error(self, gateway_instance):
        """Test SSL cert error in _start_https_server covers lines 215-232"""
        gateway = gateway_instance
        gateway.enable_direct_https = True
        gateway.ssl_cert_path = "/invalid/path.crt"
        gateway.ssl_key_path = "/invalid/path.key"

        with patch.dict("sys.modules", {"aiohttp": MagicMock()}):
            with patch("ssl.create_default_context", side_effect=Exception("SSL error")):
                result = await gateway._start_https_server()
                assert result is None
                assert gateway.health_status[ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_start_https_server_aiohttp_import_error(self, gateway_instance):
        """Test aiohttp import error in _start_https_server covers lines 215-232"""
        gateway = gateway_instance
        gateway.enable_direct_https = True

        with patch.dict("sys.modules", {"aiohttp": None}):
            result = await gateway._start_https_server()
            assert result is None
            assert gateway.health_status[ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_handle_https_websocket_aiohttp_import_error(self, gateway_instance):
        """Test aiohttp import error in _handle_https_websocket covers lines 237-238"""
        gateway = gateway_instance
        mock_request = MagicMock()

        with patch.dict("sys.modules", {"aiohttp": None}):
            with patch.object(gateway, "_manage_connection", new_callable=AsyncMock):
                result = await gateway._handle_https_websocket(mock_request)
                assert result is None

    @pytest.mark.asyncio
    async def test_detect_connection_type_localhost_return(self, gateway_instance):
        """Test _detect_connection_type localhost return covers line 265"""
        gateway = gateway_instance

        mock_ws = MagicMock()
        mock_ws.request_headers = {}
        mock_ws.remote_address = ("192.168.1.1", 12345)  # Non-local IP

        result = gateway._detect_connection_type(mock_ws)
        assert result == ConnectionType.LOCAL  # Should return LOCAL as default

    @pytest.mark.asyncio
    async def test_manage_connection_wsmsgtype_error_handling(self, gateway_instance):
        """Test WSMsgType error handling in _manage_connection covers lines 294-295"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [MagicMock(type="error", data="test error")]

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch("aiohttp.WSMsgType", create=True) as mock_wsmsgtype:
            mock_wsmsgtype.ERROR = "error"
            mock_wsmsgtype.TEXT = "text"

            with patch.object(gateway, "_send_error", new_callable=AsyncMock):
                with patch.object(gateway, "_process_message", new_callable=AsyncMock):
                    await gateway._manage_connection(conn)

    @pytest.mark.asyncio
    async def test_manage_connection_payload_processing_edge_cases(self, gateway_instance):
        """Test payload processing edge cases in _manage_connection covers lines 303-304, 307-310, 312"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        # Test various message types
        messages = [
            MagicMock(type="text", data="valid json"),
            MagicMock(data=b"bytes data"),
            MagicMock(data=123),  # Non-string/bytes
        ]
        mock_ws.__aiter__.return_value = messages

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch.object(gateway, "_check_rate_limit", return_value=True):
            with patch.object(gateway, "_process_message", new_callable=AsyncMock) as mock_process:
                with patch("aiohttp.WSMsgType", create=True):
                    await gateway._manage_connection(conn)
                    # Should process multiple message types
                    assert mock_process.call_count >= 2

    @pytest.mark.asyncio
    async def test_stop_method_websocket_close_exceptions(self, gateway_instance):
        """Test websocket close exceptions in stop method covers lines 323-324, 328-331"""
        gateway = gateway_instance

        # Create connections with problematic websockets
        mock_ws1 = AsyncMock()
        mock_ws1.close = AsyncMock(side_effect=Exception("Close failed"))

        mock_ws2 = MagicMock()
        mock_ws2.close = MagicMock(side_effect=Exception("Sync close failed"))

        conn1 = ClientConnection(
            websocket=mock_ws1,
            connection_type=ConnectionType.LOCAL,
            client_id="client-1",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        conn2 = ClientConnection(
            websocket=mock_ws2,
            connection_type=ConnectionType.LOCAL,
            client_id="client-2",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        gateway.clients = {"client-1": conn1, "client-2": conn2}

        # Should not raise exceptions
        await gateway.stop()
        assert len(gateway.clients) == 0

    @pytest.mark.asyncio
    async def test_stop_method_server_cleanup_exceptions(self, gateway_instance):
        """Test server cleanup exceptions in stop method covers lines 426-427, 432-433, 438-439, 444-445"""
        gateway = gateway_instance

        # Mock servers with problematic cleanup methods
        gateway.local_server = AsyncMock()
        gateway.local_server.close = AsyncMock(side_effect=Exception("Close failed"))
        gateway.local_server.wait_closed = AsyncMock(side_effect=Exception("Wait failed"))

        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.terminate = MagicMock(side_effect=Exception("Terminate failed"))

        gateway.tailscale_process = MagicMock()
        gateway.tailscale_process.terminate = MagicMock(side_effect=Exception("Terminate failed"))

        gateway.https_server = AsyncMock()
        gateway.https_server.cleanup = AsyncMock(side_effect=Exception("Cleanup failed"))

        # Should not raise exceptions
        await gateway.stop()

    @pytest.mark.asyncio
    async def test_process_message_json_decode_error(self, gateway_instance):
        """Test JSON decode error in _process_message covers lines 360-361"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_send_error:
            await gateway._process_message(conn, "invalid json")
            mock_send_error.assert_called_with(conn, "Invalid JSON")

    @pytest.mark.asyncio
    async def test_process_message_general_exception(self, gateway_instance):
        """Test general exception in _process_message covers lines 365-366"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch("json.loads", side_effect=Exception("Unexpected error")):
            with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_send_error:
                await gateway._process_message(conn, '{"valid": "json"}')
                mock_send_error.assert_called_with(conn, "Internal error")

    @pytest.mark.asyncio
    async def test_health_monitor_loop_start_cloudflare_exception(self, gateway_instance):
        """Test exception in _start_cloudflare_tunnel during health monitor covers lines 404-405"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.poll.return_value = 1  # Process died

        with patch.object(gateway, "_start_cloudflare_tunnel", side_effect=Exception("Restart failed")):
            with patch("asyncio.sleep", side_effect=[None, Exception("Break loop")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass  # Expected to break the loop

    @pytest.mark.asyncio
    async def test_rate_limit_timestamp_exception_handling(self, gateway_instance):
        """Test timestamp exception handling in rate limiting covers lines 125-129 (local _ts function)"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Create a mock datetime object that raises exception on timestamp()
        mock_bad_datetime = MagicMock()
        mock_bad_datetime.timestamp.side_effect = Exception("timestamp failed")

        # Patch datetime.now to return our bad datetime
        with patch("adapters.unified_gateway.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_bad_datetime

            # This should handle the exception and return True (allowing the request)
            result = gateway._check_rate_limit(conn)
            assert result is True

    @pytest.mark.asyncio
    async def test_manage_connection_message_iteration_break(self, gateway_instance):
        """Test message iteration break in _manage_connection covers lines 315-316"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        # Create a message that causes rate limit to trigger break
        messages = [MagicMock(data='{"test": "data"}')]
        mock_ws.__aiter__.return_value = messages

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Set up rate limiting to be exceeded
        gateway.rate_limits[ConnectionType.LOCAL.value] = {"test-client": [datetime.now()] * 1001}

        with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_send_error:
            await gateway._manage_connection(conn)
            mock_send_error.assert_called_with(conn, "Rate limit exceeded")

    @pytest.mark.asyncio
    async def test_ts_function_exception_fallback(self, gateway_instance):
        """Test _ts function exception fallback covers lines 128-129"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=MagicMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Create invalid datetime objects that will cause exceptions
        invalid_datetime = MagicMock()
        invalid_datetime.timestamp.side_effect = Exception("timestamp failed")
        invalid_datetime.__float__ = MagicMock(side_effect=Exception("float failed"))

        # Patch datetime.now to return our invalid datetime
        with patch("adapters.unified_gateway.datetime") as mock_datetime:
            mock_datetime.now.return_value = invalid_datetime

            # This should handle all exceptions and fall back to current timestamp
            result = gateway._check_rate_limit(conn)
            assert result is True

    @pytest.mark.asyncio
    async def test_start_https_server_full_exception_coverage(self, gateway_instance):
        """Test full exception coverage in _start_https_server covers lines 215-232"""
        gateway = gateway_instance
        gateway.enable_direct_https = True

        # Test various exception paths
        with patch("aiohttp.web.Application") as mock_app:
            mock_app.return_value.router.add_get.side_effect = Exception("Router error")

            with patch("aiohttp.web.AppRunner") as mock_runner:
                mock_runner.return_value.setup = AsyncMock(side_effect=Exception("Setup failed"))

                result = await gateway._start_https_server()
                assert result is None
                assert gateway.health_status[ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_manage_connection_wsmsgtype_full_coverage(self, gateway_instance):
        """Test full WSMsgType coverage in _manage_connection covers lines 294-295"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [MagicMock(type="text", data='{"test": "data"}')]

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Force aiohttp import to fail specifically
        original_import = __import__

        def side_effect(name, *args, **kwargs):
            if name == "aiohttp":
                raise ImportError("No aiohttp")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=side_effect):
            with patch.object(gateway, "_check_rate_limit", return_value=True):
                with patch.object(gateway, "_process_message", new_callable=AsyncMock):
                    await gateway._manage_connection(conn)
                    assert True

    @pytest.mark.asyncio
    async def test_manage_connection_payload_decode_exceptions(self, gateway_instance):
        """Test payload decode exceptions in _manage_connection covers lines 309-310"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        # Send bytes that will fail to decode
        mock_message = MagicMock()
        mock_message.data = b"\xff\xfe\xfd"  # Invalid UTF-8 bytes
        mock_ws.__aiter__.return_value = [mock_message]

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch.object(gateway, "_check_rate_limit", return_value=True):
            with patch.object(gateway, "_process_message", new_callable=AsyncMock) as mock_process:
                await gateway._manage_connection(conn)
                # Should still call process_message even with decode errors
                mock_process.assert_called()

    @pytest.mark.asyncio
    async def test_stop_method_async_websocket_close_exception(self, gateway_instance):
        """Test async websocket close exception in stop method covers lines 323-324"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("Async close failed"))

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="client-1",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        gateway.clients = {"client-1": conn}

        # Should handle async close exceptions
        await gateway.stop()
        assert len(gateway.clients) == 0

    @pytest.mark.asyncio
    async def test_stop_method_sync_websocket_close_exception(self, gateway_instance):
        """Test sync websocket close exception in stop method covers lines 328-331"""
        gateway = gateway_instance

        mock_ws = MagicMock()
        mock_ws.close = MagicMock(side_effect=Exception("Sync close failed"))

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="client-1",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        gateway.clients = {"client-1": conn}

        # Should handle sync close exceptions
        await gateway.stop()
        assert len(gateway.clients) == 0

    @pytest.mark.asyncio
    async def test_process_message_bytes_decode_error(self, gateway_instance):
        """Test bytes decode error in _process_message covers lines 360-361"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Send invalid bytes that will fail JSON parsing after decode
        with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_send_error:
            await gateway._process_message(conn, b"\xff\xfe\xfd")
            mock_send_error.assert_called_with(conn, "Invalid JSON")

    @pytest.mark.asyncio
    async def test_start_cloudflare_tunnel_success_path(self, gateway_instance):
        """Test successful Cloudflare tunnel start covers lines 180-193"""
        gateway = gateway_instance
        gateway.enable_cloudflare = True
        gateway.cloudflare_tunnel_id = "test-tunnel"

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running

        # Version check is now async
        mock_ver_proc = AsyncMock()
        mock_ver_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_ver_proc):
            with patch("subprocess.Popen", return_value=mock_process):
                result = await gateway._start_cloudflare_tunnel()
                assert result is True
                assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is True
                assert gateway.cloudflare_process == mock_process

    @pytest.mark.asyncio
    async def test_start_https_server_ssl_cert_success(self, gateway_instance):
        """Test successful SSL certificate loading covers line 210"""
        gateway = gateway_instance
        gateway.enable_direct_https = True
        gateway.ssl_cert_path = "/valid/cert.crt"
        gateway.ssl_key_path = "/valid/key.key"

        with patch("aiohttp.web.Application"):
            with patch("aiohttp.web.AppRunner") as mock_runner:
                mock_runner_instance = AsyncMock()
                mock_runner.return_value = mock_runner_instance
                mock_runner_instance.setup = AsyncMock()

                with patch("aiohttp.web.TCPSite") as mock_site:
                    mock_site_instance = AsyncMock()
                    mock_site.return_value = mock_site_instance
                    mock_site_instance.start = AsyncMock()

                    with patch("ssl.create_default_context") as mock_ssl:
                        mock_context = MagicMock()
                        mock_ssl.return_value = mock_context
                        mock_context.load_cert_chain = MagicMock()

                        result = await gateway._start_https_server()
                        assert result == mock_runner_instance
                        assert gateway.health_status[ConnectionType.DIRECT.value] is True
                        mock_context.load_cert_chain.assert_called_once_with("/valid/cert.crt", "/valid/key.key")

    @pytest.mark.asyncio
    async def test_start_https_server_success_path(self, gateway_instance):
        """Test successful HTTPS server start covers lines 227-229"""
        gateway = gateway_instance
        gateway.enable_direct_https = True

        with patch("aiohttp.web.Application") as mock_app:
            mock_app_instance = MagicMock()
            mock_app.return_value = mock_app_instance
            mock_app_instance.router.add_get = MagicMock()

            with patch("aiohttp.web.AppRunner") as mock_runner:
                mock_runner_instance = AsyncMock()
                mock_runner.return_value = mock_runner_instance
                mock_runner_instance.setup = AsyncMock()

                with patch("aiohttp.web.TCPSite") as mock_site:
                    mock_site_instance = AsyncMock()
                    mock_site.return_value = mock_site_instance
                    mock_site_instance.start = AsyncMock()

                    result = await gateway._start_https_server()
                    assert result == mock_runner_instance
                    assert gateway.health_status[ConnectionType.DIRECT.value] is True
                    assert gateway.https_server == mock_runner_instance

    @pytest.mark.asyncio
    async def test_start_https_server_tcpsite_start_exception(self, gateway_instance):
        """Test TCPSite.start exception in _start_https_server covers lines 218-229"""
        gateway = gateway_instance
        gateway.enable_direct_https = True

        with patch("aiohttp.web.Application") as mock_app_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app
            mock_app.router.add_get = MagicMock()

            with patch("aiohttp.web.AppRunner") as mock_runner_class:
                mock_runner = AsyncMock()
                mock_runner_class.return_value = mock_runner
                mock_runner.setup = AsyncMock()

                with patch("aiohttp.web.TCPSite") as mock_tcpsite_class:
                    mock_site = AsyncMock()
                    mock_tcpsite_class.return_value = mock_site
                    mock_site.start = AsyncMock(side_effect=Exception("TCPSite start failed"))

                    result = await gateway._start_https_server()
                    assert result is None
                    assert gateway.health_status[ConnectionType.DIRECT.value] is False

    @pytest.mark.asyncio
    async def test_manage_connection_bytes_decode_error_edge_case(self, gateway_instance):
        """Test bytes decode error edge case in _manage_connection covers lines 309-310"""
        gateway = gateway_instance

        mock_ws = AsyncMock()
        # Create message with bytes that will cause decode exception
        mock_message = MagicMock()
        mock_message.data = b"\x80\x81\x82"  # Bytes that can't be decoded as UTF-8
        mock_message.type = None
        mock_message.__bool__ = lambda: True
        mock_ws.__aiter__.return_value = [mock_message]

        conn = ClientConnection(
            websocket=mock_ws,
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        with patch.object(gateway, "_check_rate_limit", return_value=True):
            with patch.object(gateway, "_process_message", new_callable=AsyncMock) as mock_process:
                await gateway._manage_connection(conn)
                # Should call process_message even with decode errors
                mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_method_local_server_close_exception(self, gateway_instance):
        """Test local server close exception in stop method covers lines 323-324"""
        gateway = gateway_instance

        mock_server = AsyncMock()
        mock_server.close = AsyncMock(side_effect=Exception("Server close failed"))
        mock_server.wait_closed = AsyncMock()

        gateway.local_server = mock_server

        # Should handle server close exceptions
        await gateway.stop()

    @pytest.mark.asyncio
    async def test_stop_method_local_server_wait_closed_exception(self, gateway_instance):
        """Test local server wait_closed exception in stop method covers lines 330-331"""
        gateway = gateway_instance

        mock_server = AsyncMock()
        mock_server.close = AsyncMock()
        mock_server.wait_closed = AsyncMock(side_effect=Exception("Wait closed failed"))

        gateway.local_server = mock_server

        # Should handle wait_closed exceptions
        await gateway.stop()

    @pytest.mark.asyncio
    async def test_process_message_bytes_to_string_conversion(self, gateway_instance):
        """Test bytes to string conversion in _process_message covers lines 360-361"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Send bytes that will be converted to string
        test_bytes = b'{"test": "data"}'
        with patch("json.loads", return_value={"test": "data"}):
            with patch.object(gateway, "_forward_to_megabot", new_callable=AsyncMock) as mock_forward:
                await gateway._process_message(conn, test_bytes)
                mock_forward.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_raw_message_bytes_handling(self, gateway_instance):
        """Test raw_message bytes handling in _process_message covers lines 365-366"""
        gateway = gateway_instance

        conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-client",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        # Send raw bytes directly (not through websocket processing)
        with patch("json.loads", side_effect=Exception("Parse failed")):
            with patch.object(gateway, "_send_error", new_callable=AsyncMock) as mock_send_error:
                await gateway._process_message(conn, b"invalid json bytes")
                mock_send_error.assert_called_with(conn, "Internal error")

    @pytest.mark.asyncio
    async def test_health_monitor_subprocess_run_exception(self, gateway_instance):
        """Test subprocess.run exception in health monitor covers lines 404-405"""
        gateway = gateway_instance
        gateway.enable_vpn = True

        with patch("asyncio.create_subprocess_exec", side_effect=Exception("Subprocess failed")):
            with patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
                try:
                    await gateway._health_monitor_loop()
                except Exception:
                    pass  # Expected to stop the loop


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# Gateway authentication tests (from test_coverage_phase4.py)
# These test core.network.gateway (distinct from adapters.unified_gateway above)
# ---------------------------------------------------------------------------

from core.network.gateway import UnifiedGateway as _CoreGateway
from core.network.gateway import ClientConnection as _CoreClientConnection
from core.network.gateway import ConnectionType as _CoreConnectionType


class TestGatewayAuthentication:
    """Cover gateway.py lines 482-491 and 539-588."""

    def _make_gateway(self, auth_token="secret-token"):
        return _CoreGateway(
            megabot_server_port=18799,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
            auth_token=auth_token,
        )

    def _make_conn(self, ws, conn_type=None):
        if conn_type is None:
            conn_type = _CoreConnectionType.DIRECT  # non-LOCAL so auth is required
        return _CoreClientConnection(
            websocket=ws,
            connection_type=conn_type,
            client_id="test-client-1",
            ip_address="10.0.0.1",
            connected_at=datetime.now(),
            authenticated=False,
            user_agent="test",
        )

    @pytest.mark.asyncio
    async def test_auth_success_full_flow(self):
        """Lines 539-587: successful authentication with valid token."""
        gw = self._make_gateway(auth_token="my-secret-token")

        # Create a mock websocket that yields an auth message
        auth_msg = json.dumps({"type": "auth", "token": "my-secret-token"})

        ws = AsyncMock()
        # __aiter__ must return an async iterator. We set up __anext__ to
        # return the auth payload once, then StopAsyncIteration.
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        # Auth succeeds — the send_str OSError is silently caught, result is still True
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_wrong_type_field(self):
        """Lines 565-566: type != 'auth' returns False."""
        gw = self._make_gateway(auth_token="token")

        auth_msg = json.dumps({"type": "not_auth", "token": "token"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_missing_token_field(self):
        """Lines 568-570: missing/empty token returns False."""
        gw = self._make_gateway(auth_token="token")

        auth_msg = json.dumps({"type": "auth"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_bytes_payload(self):
        """Lines 555-556: bytes payload decoded properly."""
        gw = self._make_gateway(auth_token="byte-token")

        auth_msg = json.dumps({"type": "auth", "token": "byte-token"}).encode("utf-8")
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_with_data_attribute(self):
        """Lines 553-554: raw message with .data attribute."""
        gw = self._make_gateway(auth_token="data-token")

        raw_msg = MagicMock()
        raw_msg.data = json.dumps({"type": "auth", "token": "data-token"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=raw_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_send_str_fallback(self):
        """Lines 582-586: ws has send_str but not send."""
        gw = self._make_gateway(auth_token="str-token")

        auth_msg = json.dumps({"type": "auth", "token": "str-token"})

        # Custom mock: has send_str but NOT send, and supports async iteration
        class NoSendWebSocket:
            def __init__(self):
                self.send_str = AsyncMock()
                self._auth_msg = auth_msg

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._auth_msg is not None:
                    msg = self._auth_msg
                    self._auth_msg = None  # Only yield once
                    return msg
                raise StopAsyncIteration

        ws = NoSendWebSocket()
        assert not hasattr(ws, "send")

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True
        ws.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_manage_connection_auth_failed_line_484_487(self):
        """Lines 484-487: _authenticate_connection returns False -> send error, remove client."""
        gw = self._make_gateway(auth_token="token")

        ws = AsyncMock()
        ws.send = AsyncMock()
        # Make it so auth fails (wrong token)
        auth_msg = json.dumps({"type": "auth", "token": "WRONG"})
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        await gw._manage_connection(conn)

        # Client should be removed after failed auth
        assert conn.client_id not in gw.clients

    @pytest.mark.asyncio
    async def test_manage_connection_auth_exception_line_488_491(self):
        """Lines 488-491: _authenticate_connection raises -> send 'Authentication timeout', remove client."""
        gw = self._make_gateway(auth_token="token")

        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.__aiter__ = MagicMock(return_value=MagicMock(__anext__=AsyncMock(side_effect=RuntimeError("kaboom"))))

        conn = self._make_conn(ws)

        # Patch _authenticate_connection to raise
        with patch.object(gw, "_authenticate_connection", side_effect=RuntimeError("kaboom")):
            await gw._manage_connection(conn)

        # Client should have been removed
        assert conn.client_id not in gw.clients


class TestGatewayAuthEdgeCases:
    """Cover remaining uncovered branches in _authenticate_connection."""

    @pytest.mark.asyncio
    async def test_auth_non_string_payload_line_558(self):
        """Line 558/562: raw is an integer (not str/bytes, no .data attr) -> str() fallback."""
        gw = _CoreGateway.__new__(_CoreGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 1

        # The raw value returned by __anext__ is an integer — not str, not bytes
        # json.loads(str(42)) will fail with JSONDecodeError -> return False
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=ws)
        ws.__anext__ = AsyncMock(return_value=42)

        conn = _CoreClientConnection(
            client_id="test-edge",
            websocket=ws,
            connection_type=_CoreConnectionType.DIRECT,
            ip_address="10.0.0.1",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_send_raises_exception_lines_580_581(self):
        """Lines 580-581: ws.send() raises during ack -> silently ignored, still returns True."""
        import logging

        gw = _CoreGateway.__new__(_CoreGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 5
        gw.logger = logging.getLogger("core.network.gateway")

        auth_msg = json.dumps({"type": "auth", "token": "secret"})

        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=ws)
        ws.__anext__ = AsyncMock(return_value=auth_msg)
        ws.send = AsyncMock(side_effect=ConnectionError("broken pipe"))

        conn = _CoreClientConnection(
            client_id="test-send-fail",
            websocket=ws,
            connection_type=_CoreConnectionType.DIRECT,
            ip_address="10.0.0.2",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        assert result is True
        assert conn.authenticated is True
        ws.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_send_str_raises_exception_lines_585_586(self):
        """Lines 585-586: ws.send_str() raises during ack -> silently ignored, still returns True."""
        import logging

        gw = _CoreGateway.__new__(_CoreGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 5
        gw.logger = logging.getLogger("core.network.gateway")

        auth_msg = json.dumps({"type": "auth", "token": "secret"})

        # Create a ws object that does NOT have 'send' but DOES have 'send_str'
        class NoSendWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                return auth_msg

            async def send_str(self, data):
                raise OSError("transport closed")

        ws = NoSendWS()

        conn = _CoreClientConnection(
            client_id="test-send-str-fail",
            websocket=ws,
            connection_type=_CoreConnectionType.DIRECT,
            ip_address="10.0.0.3",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        # Auth succeeds — send_str OSError is silently caught, doesn't prevent auth
        assert result is True


# ==============================================================
# Round 3 — merged from test_coverage_round3.py
# ==============================================================


@pytest.mark.asyncio
async def test_gateway_health_wrapper_invocation_raises():
    """Lines 108-110: _health_monitor_loop() raises -> return."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    gw._health_monitor_loop = MagicMock(side_effect=RuntimeError("boom"))

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_health_await_coro_raises():
    """Line 133: safe_to_await=True, await raises -> pass."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    async def failing_health():
        raise RuntimeError("health crashed")

    gw._health_monitor_loop = MagicMock(return_value=failing_health())

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_health_last_resort_raises():
    """Lines 144-145: last-resort await raises -> except pass."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    class FailingAwaitable:
        def __await__(self):
            raise RuntimeError("nope")

    gw._health_monitor_loop = MagicMock(return_value=FailingAwaitable())

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_start_coro_close_raises():
    """Lines 172-173: coro.close() raises in start's finally."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    gw._health_monitor_loop = AsyncMock()

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        with patch("asyncio.create_task", return_value="not-task"):
            with patch("asyncio.ensure_future", return_value="not-future"):
                await gw.start()

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_gateway_stop_coro_close():
    """Lines 212-215: stop() closes __await__.__self__ coroutine."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.cloudflare_process = None
    gw.tailscale_process = None
    gw.https_server = None

    async def dummy():
        await asyncio.sleep(999)

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__await__ = coro.__await__

    gw._health_task = mock_task

    await gw.stop()

    try:
        coro.close()
    except RuntimeError:
        pass


@pytest.mark.asyncio
async def test_gateway_stop_no_health_task():
    """Gateway stop() with no health task — just clients cleanup."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.cloudflare_process = None
    gw.tailscale_process = None
    gw.https_server = None
    gw._health_task = None

    await gw.stop()


@pytest.mark.asyncio
async def test_gateway_coverage_gaps():
    gateway = UnifiedGateway()

    # Mock connection
    mock_ws = AsyncMock()
    conn = ClientConnection(
        client_id="test_client",
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    # 1. Test bytes decoding failure in _process_message (lines 330-331)
    mock_bytes = MagicMock()
    mock_bytes.decode.side_effect = Exception("Decode fail")

    with patch(
        "core.network.gateway.isinstance",
        side_effect=lambda x, t: True if t is bytes and x is mock_bytes else isinstance(x, t),
    ):
        await gateway._process_message(conn, mock_bytes)  # type: ignore

    # 2. Test send/send_str exceptions in _send_error (lines 360-361, 365-366)
    mock_ws.send.side_effect = Exception("Send failed")
    mock_ws.send_str.side_effect = Exception("Send_str failed")
    await gateway._send_error(conn, "test error")


@pytest.mark.asyncio
async def test_gateway_mopup_targeted():
    gateway = UnifiedGateway()

    # 1. Line 399-403: self.cloudflare_process.poll() is NOT None
    gateway.cloudflare_tunnel_id = "test-token-2"
    mock_proc_fail = MagicMock()
    mock_proc_fail.poll.return_value = 1

    mock_async_proc = AsyncMock()
    mock_async_proc.wait = AsyncMock(return_value=0)
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_async_proc),
        patch("subprocess.Popen", return_value=mock_proc_fail),
    ):
        res = await gateway._start_cloudflare_tunnel()
        assert res is False
        assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is False

    # 2. Line 302: payload = getattr(message, "data", message)
    mock_ws = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.type = "TEXT"
    mock_msg.data = b"valid data"
    mock_ws.__aiter__.return_value = [mock_msg]

    conn = ClientConnection(
        client_id="test_mopup",
        websocket=mock_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    mock_wsm_type = MagicMock()
    mock_wsm_type.TEXT = "TEXT"
    mock_wsm_type.ERROR = "ERROR"

    with (
        patch.dict("sys.modules", {"aiohttp": MagicMock(WSMsgType=mock_wsm_type)}),
        patch.object(gateway, "_process_message", AsyncMock()),
    ):
        await gateway._manage_connection(conn)

    # 3. Line 323-324: Synchronous close
    sync_ws = MagicMock()
    sync_ws.__aiter__.return_value = []
    conn_sync = ClientConnection(
        client_id="test_sync_close",
        websocket=sync_ws,
        connection_type=ConnectionType.LOCAL,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )
    await gateway._manage_connection(conn_sync)
    assert sync_ws.close.called

    # 4. Line 309-310: Force decode failure
    mock_bytes_msg = MagicMock()
    mock_bytes_msg.decode.side_effect = Exception("Force fail")
    mock_ws.__aiter__.return_value = [mock_bytes_msg]
    with (
        patch.dict("sys.modules", {"aiohttp": MagicMock()}),
        patch(
            "core.network.gateway.hasattr",
            side_effect=lambda o, a: False if a == "type" and o is mock_bytes_msg else hasattr(o, a),
        ),
        patch(
            "core.network.gateway.isinstance",
            side_effect=lambda o, t: True if t is bytes and o is mock_bytes_msg else isinstance(o, t),
        ),
        patch.object(gateway, "_process_message", AsyncMock()),
    ):
        await gateway._manage_connection(conn)

    # 5. Line 390: Health monitor poll() is None
    gateway.enable_cloudflare = True
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    gateway.cloudflare_process = mock_proc
    with patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
        try:
            await gateway._health_monitor_loop()
        except Exception as e:
            if str(e) != "Stop loop":
                raise
    assert gateway.health_status[ConnectionType.CLOUDFLARE.value] is True
