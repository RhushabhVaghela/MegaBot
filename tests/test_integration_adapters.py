"""
Integration tests for all messaging adapters
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from megabot.adapters.messaging.telegram import TelegramAdapter
from megabot.adapters.push_notification_adapter import (
    PushNotificationAdapter,
    create_notification,
)
from megabot.adapters.signal_adapter import SignalAdapter
from megabot.adapters.unified_gateway import ClientConnection, ConnectionType, UnifiedGateway


class TestMessagingIntegration:
    """Integration tests for messaging system"""

    @pytest.fixture
    def adapters(self):
        # Telegram (messaging adapter requires server param)
        tg = TelegramAdapter(bot_token="test_tg", server=MagicMock())
        tg.session = MagicMock()

        # Signal
        sig = SignalAdapter(phone_number="+919601777533")
        sig.is_initialized = True

        # Push
        push = PushNotificationAdapter(fcm_project_id="test_push")
        push._is_initialized = True

        return {"tg": tg, "sig": sig, "push": push}

    @pytest.fixture
    def gateway(self):
        """Unified gateway instance for integration testing"""
        gateway = UnifiedGateway(
            megabot_server_port=18791,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
        )
        return gateway

    @pytest.mark.asyncio
    async def test_send_to_indian_number(self, adapters):
        """Test sending to the specified Indian number across platforms"""
        indian_number = "+919601777533"

        # 1. Telegram
        with patch.object(adapters["tg"], "_make_request", new_callable=AsyncMock) as m:
            m.return_value = {"message_id": 1}
            await adapters["tg"].send_text(
                chat_id=indian_number, text="Integration Test"
            )
            m.assert_called_once()

        # 2. Signal
        with patch.object(
            adapters["sig"], "_send_json_rpc", new_callable=AsyncMock
        ) as m:
            m.return_value = {"envelopeId": "1"}
            await adapters["sig"].send_message(
                recipient=indian_number, message="Integration Test"
            )
            m.assert_called_once()

        # 3. Push
        with patch.object(
            adapters["push"], "send_to_token", new_callable=AsyncMock
        ) as m:
            from megabot.adapters.push_notification_adapter import NotificationResult, Platform

            m.return_value = NotificationResult(success=True)

            # Register token for the number first
            await adapters["push"].register_token(
                token="t1", platform=Platform.ANDROID, user_id=indian_number
            )

            notif = create_notification("MegaBot", "Integration Test")
            res = await adapters["push"].send_to_user(
                user_id=indian_number, notification=notif
            )

            assert res.success is True
            m.assert_called_once()

    @pytest.mark.asyncio
    async def test_gateway_routing_integration(self, gateway):
        """Test unified gateway routing with different connection types"""
        # Test local connection
        mock_ws_local = AsyncMock()
        mock_ws_local.remote_address = ("127.0.0.1", 54321)
        mock_ws_local.request_headers = {}
        mock_ws_local.__aiter__.return_value = []

        with patch.object(
            gateway, "_manage_connection", new_callable=AsyncMock
        ) as mock_manage:
            await gateway._handle_websocket(mock_ws_local, "")
            mock_manage.assert_called_once()
            # Verify local connection type
            call_args = mock_manage.call_args[0][0]
            assert call_args.connection_type.value == "local"

        # Test Cloudflare connection
        mock_ws_cf = AsyncMock()
        mock_ws_cf.remote_address = ("203.0.113.1", 44321)
        mock_ws_cf.request_headers = {"CF-Connecting-IP": "1.2.3.4"}
        mock_ws_cf.__aiter__.return_value = []

        with patch.object(
            gateway, "_manage_connection", new_callable=AsyncMock
        ) as mock_manage:
            await gateway._handle_websocket(mock_ws_cf, "")
            mock_manage.assert_called_once()
            call_args = mock_manage.call_args[0][0]
            assert call_args.connection_type.value == "cloudflare"
            assert call_args.ip_address == "1.2.3.4"  # Should use CF header

        # Test VPN connection
        mock_ws_vpn = AsyncMock()
        mock_ws_vpn.remote_address = ("100.64.0.1", 44321)  # Tailscale IP range
        mock_ws_vpn.request_headers = {}
        mock_ws_vpn.__aiter__.return_value = []

        with patch.object(
            gateway, "_manage_connection", new_callable=AsyncMock
        ) as mock_manage:
            await gateway._handle_websocket(mock_ws_vpn, "")
            mock_manage.assert_called_once()
            call_args = mock_manage.call_args[0][0]
            assert call_args.connection_type.value == "vpn"

    @pytest.mark.asyncio
    async def test_gateway_rate_limiting_integration(self, gateway):
        """Test rate limiting works across different connection types"""
        # Test local connection rate limiting
        conn_local = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-local",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )
        assert gateway._check_rate_limit(conn_local) is True

        # Exhaust local limit
        for _ in range(1000):
            gateway._check_rate_limit(conn_local)

        assert gateway._check_rate_limit(conn_local) is False

        # Test VPN rate limiting (different limits)
        conn_vpn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.VPN,
            client_id="test-vpn",
            ip_address="100.64.0.1",
            connected_at=datetime.now(),
        )
        assert gateway._check_rate_limit(conn_vpn) is True

        # VPN should have different limits
        for _ in range(500):
            gateway._check_rate_limit(conn_vpn)

        assert gateway._check_rate_limit(conn_vpn) is False

    @pytest.mark.asyncio
    async def test_gateway_health_monitoring_integration(self, gateway):
        """Test health monitoring updates status correctly"""
        # Initially all disabled, so health should be False
        assert gateway.health_status["cloudflare"] is False
        assert gateway.health_status["vpn"] is False
        assert gateway.health_status["direct"] is False
        assert gateway.health_status["local"] is True  # Local is always healthy

        # Enable Cloudflare and test monitoring
        gateway.enable_cloudflare = True
        gateway.cloudflare_process = MagicMock()
        gateway.cloudflare_process.poll.return_value = None  # Running

        with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
            try:
                await gateway._health_monitor_loop()
            except Exception:
                pass

        # Cloudflare should be healthy
        assert gateway.health_status["cloudflare"] is True

    @pytest.mark.asyncio
    async def test_full_messaging_flow_simulation(self, adapters, gateway):
        """Simulate a full messaging flow from gateway to adapters"""
        indian_number = "+919601777533"

        # Mock message handler
        received_messages = []

        async def mock_message_handler(data):
            received_messages.append(data)

        gateway.on_message = mock_message_handler

        # Create a mock connection
        mock_conn = ClientConnection(
            websocket=AsyncMock(),
            connection_type=ConnectionType.LOCAL,
            client_id="test-flow",
            ip_address="127.0.0.1",
            connected_at=datetime.now(),
        )

        test_message = {
            "type": "text",
            "content": "Hello from integration test",
            "recipient": indian_number,
            "platform": "telegram",
        }

        # Process the message directly
        await gateway._process_message(mock_conn, json.dumps(test_message))

        # Verify message was forwarded
        assert len(received_messages) == 1
        msg = received_messages[0]
        assert msg["type"] == "text"
        assert msg["content"] == "Hello from integration test"
        assert msg["_meta"]["connection_type"] == "local"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
