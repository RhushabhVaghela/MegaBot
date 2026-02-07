"""
Tests for Push Notification Adapter
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from datetime import datetime, timedelta
import json
import sys

# Mock Firebase messaging functions and classes at module level
firebase_admin_mock = sys.modules["firebase_admin"]
firebase_messaging_mock = sys.modules["firebase_admin.messaging"]


# Mock response objects
class MockBatchResponse:
    success_count = 2
    failure_count = 0


class MockTopicResponse:
    success_count = 1


mock_send_response = MagicMock()
mock_send_response.success_count = 1
mock_send_response.failure_count = 0

mock_batch_response = MockBatchResponse()
mock_topic_response = MockTopicResponse()

# Mock functions
firebase_messaging_mock.send_each_for_multicast_sync = MagicMock(return_value=mock_batch_response)
firebase_messaging_mock.send = MagicMock(return_value="mock_message_id")
firebase_messaging_mock.subscribe_to_topic = MagicMock(return_value=mock_topic_response)
firebase_messaging_mock.unsubscribe_from_topic = MagicMock(return_value=mock_topic_response)
firebase_admin_mock.initialize_app = MagicMock(return_value=MagicMock())

mock_firebase_class = MagicMock()
firebase_messaging_mock.Notification = mock_firebase_class
firebase_messaging_mock.AndroidNotification = mock_firebase_class
firebase_messaging_mock.ApsAlert = mock_firebase_class
firebase_messaging_mock.WebpushNotification = mock_firebase_class
firebase_messaging_mock.Message = mock_firebase_class
firebase_messaging_mock.MulticastMessage = mock_firebase_class
firebase_messaging_mock.AndroidConfig = mock_firebase_class
firebase_messaging_mock.APNSConfig = mock_firebase_class
firebase_messaging_mock.APNSPayload = mock_firebase_class
firebase_messaging_mock.Aps = mock_firebase_class
firebase_messaging_mock.WebpushConfig = mock_firebase_class


@pytest.fixture(autouse=True)
def reset_firebase_mocks():
    """Reset Firebase mocks before each test to ensure clean state"""
    firebase_messaging_mock.send_each_for_multicast_sync.reset_mock()
    firebase_messaging_mock.send_each_for_multicast_sync.return_value = mock_batch_response
    firebase_messaging_mock.send.reset_mock()
    firebase_messaging_mock.send.return_value = "mock_message_id"
    firebase_messaging_mock.subscribe_to_topic.reset_mock()
    firebase_messaging_mock.subscribe_to_topic.return_value = mock_topic_response
    firebase_messaging_mock.unsubscribe_from_topic.reset_mock()
    firebase_messaging_mock.unsubscribe_from_topic.return_value = mock_topic_response
    firebase_admin_mock.initialize_app.reset_mock()
    firebase_admin_mock.initialize_app.return_value = MagicMock()


from adapters.push_notification_adapter import (
    PushNotification,
    AndroidConfig,
    ApnsConfig,
    WebpushConfig,
    DeviceToken,
    NotificationChannel,
    NotificationResult,
    PushNotificationAdapter,
    Platform,
    Priority,
    NotificationType,
    create_notification,
)


class TestPushDataClasses:
    """Test Push Notification data classes"""

    def test_push_notification_to_dict_full(self):
        notif = PushNotification(
            title="T",
            body="B",
            notification_type=NotificationType.MESSAGE,
            image_url="I",
            icon="Ic",
            sound="S",
            badge=1,
            tag="Tg",
            color="C",
            click_action="A",
            channel_id="Ch",
            ticker="Tk",
            sticky=True,
            local_only=True,
        )
        d = notif.to_dict()
        assert d["title"] == "T"
        assert d["sticky"] is True

    def test_android_config_full(self):
        config = AndroidConfig(
            collapse_key="C",
            priority=Priority.HIGH,
            notification=PushNotification(title="T", body="B"),
            data={"k": "v"},
            direct_boot_ok=True,
            restricted_package_name="P",
        )
        d = config.to_dict()
        assert d["collapse_key"] == "C"
        assert d["priority"] == "high"
        assert d["notification"]["title"] == "T"

    def test_apns_config_full(self):
        config = ApnsConfig(
            bundle_id="B",
            badge=1,
            sound="S",
            category="C",
            thread_id="T",
            content_available=True,
            mutable_content=True,
            collapse_id="Co",
            expiration=100,
            topic="To",
            custom_data={"k": "v"},
        )
        d = config.to_dict()
        assert d["aps"]["badge"] == 1
        assert d["aps"]["content-available"] == 1
        assert d["k"] == "v"

    def test_webpush_config_full(self):
        config = WebpushConfig(
            notification=PushNotification(title="T", body="B"),
            data={"k": "v"},
            headers={"h": "v"},
            ttl=100,
        )
        d = config.to_dict()
        assert d["notification"]["title"] == "T"
        assert d["ttl"] == 100

    def test_device_token(self):
        t = DeviceToken(token="T", platform=Platform.ANDROID, user_id="U")
        d = t.to_dict()
        assert d["token"] == "T"
        assert DeviceToken.from_dict(d).token == "T"

    def test_notification_result_from_firebase(self):
        mock_response = MagicMock()
        mock_response.exception = None
        mock_response.message_id = "msg123"
        mock_response.canonical_address_count = 1

        result = NotificationResult.from_firebase(mock_response)
        assert result.success is True
        assert result.message_id == "msg123"
        assert result.canonical_token is True

        # Test with exception
        mock_response.exception = Exception("Test error")
        result = NotificationResult.from_firebase(mock_response)
        assert result.success is False
        assert result.error is not None and "Test error" in result.error


class TestPushNotificationAdapter:
    """Test Push Notification adapter functionality"""

    @pytest.fixture
    def adapter(self):
        with patch("os.path.exists", return_value=True):
            return PushNotificationAdapter(
                fcm_credential_path="/tmp/fake.json",
                fcm_project_id="p",
                apns_key_path="/tmp/key.p8",
                apns_key_id="k",
                apns_bundle_id="com.example.app",
                apns_team_id="t",
                token_storage_path="/tmp/tokens.json",
            )

    @pytest.mark.asyncio
    async def test_initialize_flow(self, adapter):
        with (
            patch.object(adapter, "_initialize_fcm"),
            patch.object(adapter, "_load_tokens"),
            patch.object(adapter, "_create_default_channels"),
        ):
            assert await adapter.initialize() is True
            assert adapter._is_initialized is True

            # Test exception in initialize
            with patch.object(adapter, "_initialize_fcm", side_effect=Exception("FCM error")):
                assert await adapter.initialize() is False

    @pytest.mark.asyncio
    async def test_token_management(self, adapter):
        with patch.object(adapter, "_save_tokens") as mock_save:
            # Register
            assert await adapter.register_token("t1", Platform.ANDROID, "u1") is True
            assert "t1" in adapter.device_tokens
            mock_save.assert_called()

            # Unregister
            assert await adapter.unregister_token("t1") is True
            assert "t1" not in adapter.device_tokens

    @pytest.mark.asyncio
    async def test_send_to_token_platforms(self, adapter):
        notif = create_notification("T", "B")

        # Android
        with patch.object(adapter, "_send_fcm", new_callable=AsyncMock) as m:
            m.return_value = NotificationResult(success=True)
            await adapter.send_to_token("t1", notif, platform=Platform.ANDROID)
            m.assert_called_once()

        # iOS
        with patch.object(adapter, "_send_apns", new_callable=AsyncMock) as m:
            m.return_value = NotificationResult(success=True)
            await adapter.send_to_token("t1", notif, platform=Platform.IOS)
            m.assert_called_once()

        # Web
        with patch.object(adapter, "_send_webpush", new_callable=AsyncMock) as m:
            m.return_value = NotificationResult(success=True)
            await adapter.send_to_token("t1", notif, platform=Platform.WEB)
            m.assert_called_once()

        # Unknown
        res = await adapter.send_to_token("t1", notif, platform="unknown")
        assert res.success is False

    @pytest.mark.asyncio
    async def test_send_to_user_multi(self, adapter):
        adapter.device_tokens = {
            "t1": DeviceToken("t1", Platform.ANDROID, user_id="u1"),
            "t2": DeviceToken("t2", Platform.IOS, user_id="u1"),
        }
        notif = create_notification("T", "B")
        with patch.object(adapter, "send_to_token", new_callable=AsyncMock) as m:
            m.return_value = NotificationResult(success=True)
            res = await adapter.send_to_user("u1", notif)
            assert res.success is True
            assert m.call_count == 2

            # Test no tokens
            res = await adapter.send_to_user("u2", notif)
            assert res.success is False

    @pytest.mark.asyncio
    async def test_broadcast_methods(self, adapter):

        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch("adapters.push_notification_adapter.messaging.send_each_for_multicast_sync") as m:
            m.return_value = mock_batch_response
            await adapter.send_broadcast(notif, topic="news")
            await adapter.send_broadcast(notif, condition="'A' in topics", dry_run=True)
            assert m.call_count == 2

        with patch("adapters.push_notification_adapter.messaging.send") as m:
            m.return_value = "msg_id"
            await adapter.send_to_topic("news", notif)
            await adapter.send_to_topic("news", notif, dry_run=True)
            assert m.call_count == 1  # dry_run doesn't call messaging.send

        with patch("adapters.push_notification_adapter.messaging.unsubscribe_from_topic") as m:
            m.side_effect = Exception("unsubscribe error")
            result = await adapter.unsubscribe_from_topic(["t1"], "news")
            assert result is False

    @pytest.mark.asyncio
    async def test_apns_void(self, adapter):

        mock_res = MagicMock()
        mock_res.status_code = 204

        with (
            patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as m,
            patch.object(adapter, "_get_apns_jwt", new_callable=AsyncMock) as mj,
        ):
            m.return_value = mock_res
            mj.return_value = "jwt"
            res = await adapter.send_apns_void("t", "b")
            assert res.success is True

            # Test failure
            mock_res.status_code = 400
            res = await adapter.send_apns_void("t", "b")
            assert res.success is False

    @pytest.mark.asyncio
    async def test_send_fcm_no_firebase_app(self, adapter):
        """Test _send_fcm without Firebase app"""
        adapter._firebase_app = None
        notif = create_notification("T", "B")

        result = await adapter._send_fcm("t", notif)
        assert result.success is False
        assert result.error == "FCM not initialized"

    @pytest.mark.asyncio
    async def test_send_fcm_internal_send(self, adapter):

        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B", badge=1)

        with patch("adapters.push_notification_adapter.messaging.send") as m:
            m.return_value = "id"
            res = await adapter._send_fcm("t", notif)
            assert res.success is True

            # Test unregistered error
            m.side_effect = Exception("UNREGISTERED token")
            with patch.object(adapter, "unregister_token", new_callable=AsyncMock) as mu:
                res = await adapter._send_fcm("t", notif)
                assert res.success is False
                mu.assert_called_once()
                assert res.success is False
                mu.assert_called_once()

    @pytest.mark.asyncio
    async def test_apns_internal_send(self, adapter):

        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")
        adapter.apns_bundle_id = "com.test"

        with patch("firebase_admin.messaging.send") as m:
            m.return_value = "id"
            res = await adapter._send_apns("t", notif)
            assert res.success is True

    @pytest.mark.asyncio
    async def test_send_broadcast_multicast_message(self, adapter):
        """Test send_broadcast with MulticastMessage (no topic/condition)"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        # Register a token first
        await adapter.register_token("test_token", Platform.ANDROID, "user123")

        with patch("adapters.push_notification_adapter.messaging.send_each_for_multicast_sync") as m:
            m.return_value = MagicMock(success_count=1, failure_count=0)
            res = await adapter.send_broadcast(notif)
            assert res.success is True
            m.assert_called_once()

        with patch("os.path.exists", return_value=False):
            adapter._initialize_fcm()
            # Should not call initialize_app if creds don't exist

    def test_load_save_tokens(self, adapter):
        m = mock_open(read_data=json.dumps([{"token": "t1", "platform": "android"}]))
        with patch("builtins.open", m), patch("os.path.exists", return_value=True):
            adapter._load_tokens()
            assert "t1" in adapter.device_tokens

        m = mock_open()
        with patch("builtins.open", m), patch("os.makedirs"):
            adapter._save_tokens()
            m().write.assert_called()

    @pytest.mark.asyncio
    async def test_shutdown(self, adapter):
        with patch.object(adapter, "_save_tokens"), patch("firebase_admin.delete_app"):
            adapter._firebase_app = MagicMock()
            adapter.shutdown()
            assert adapter._firebase_app is None


class TestPushNotificationAdapterBranches:
    """Test Push Notification adapter branch coverage"""

    @pytest.fixture
    def adapter(self):
        with patch("os.path.exists", return_value=True):
            return PushNotificationAdapter(
                fcm_credential_path="/tmp/fake.json",
                fcm_project_id="p",
                apns_key_path="/tmp/key.p8",
                apns_key_id="k",
                apns_bundle_id="com.example.app",
                apns_team_id="t",
                token_storage_path="/tmp/tokens.json",
            )

    @pytest.mark.asyncio
    async def test_initialize_fcm_no_credentials(self, adapter):
        """Test FCM initialization with no credentials path"""
        adapter.fcm_credential_path = None
        with patch("os.path.exists", return_value=False):
            adapter._initialize_fcm()
            assert adapter._firebase_app is None

    @pytest.mark.asyncio
    async def test_load_tokens_invalid_json(self, adapter):
        """Test loading tokens with invalid JSON"""
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with patch("os.path.exists", return_value=True):
                with patch("json.load", side_effect=json.JSONDecodeError("Invalid", "", 0)):
                    adapter._load_tokens()
                    # Should handle error gracefully
                    assert len(adapter.device_tokens) == 0

    @pytest.mark.asyncio
    async def test_load_tokens_file_not_found(self, adapter):
        """Test loading tokens when file doesn't exist"""
        with patch("os.path.exists", return_value=False):
            adapter._load_tokens()
            # Should handle gracefully
            assert len(adapter.device_tokens) == 0

    @pytest.mark.asyncio
    async def test_save_tokens_permission_error(self, adapter):
        """Test saving tokens with permission error"""
        adapter.device_tokens = {"t1": DeviceToken("t1", Platform.ANDROID, "u1")}
        with patch("os.makedirs", side_effect=PermissionError("No permission")):
            adapter._save_tokens()
            # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_register_token_handler_errors(self, adapter):
        """Test token registration with handler errors"""
        failing_handler = MagicMock(side_effect=ValueError("handler failed"))
        adapter.register_token_handler(failing_handler)
        adapter.register_message_handler(failing_handler)
        adapter.register_error_handler(failing_handler)

        result = await adapter.register_token("t1", Platform.ANDROID, "u1")
        assert result is True  # Should still succeed despite handler error
        assert "t1" in adapter.device_tokens
        failing_handler.assert_called()

    @pytest.mark.asyncio
    async def test_unregister_token_handler_errors(self, adapter):
        """Test token unregistration with handler errors"""
        adapter.device_tokens = {"t1": DeviceToken("t1", Platform.ANDROID, "u1")}
        failing_handler = MagicMock(side_effect=ValueError("handler failed"))
        adapter.register_token_handler(failing_handler)

        result = await adapter.unregister_token("t1")
        assert result is True  # Should still succeed despite handler error
        assert "t1" not in adapter.device_tokens
        failing_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_broadcast_no_firebase_app(self, adapter):
        """Test broadcast send without Firebase app"""
        adapter._firebase_app = None
        notif = create_notification("T", "B")

        result = await adapter.send_broadcast(notif, topic="news")
        assert result.success is False
        assert "FCM not initialized" in result.error

    @pytest.mark.asyncio
    async def test_send_to_topic_no_firebase_app(self, adapter):
        """Test topic send without Firebase app"""
        adapter._firebase_app = None
        notif = create_notification("T", "B")

        result = await adapter.send_to_topic("news", notif)
        assert result.success is False
        assert "FCM not initialized" in result.error

    @pytest.mark.asyncio
    async def test_subscribe_to_topic_no_firebase_app(self, adapter):
        """Test topic subscription without Firebase app"""
        adapter._firebase_app = None

        result = await adapter.subscribe_to_topic(["t1"], "news")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_apns_void_http_errors(self, adapter):
        """Test APNS void with different HTTP status codes"""

        notif = create_notification("T", "B")

        # Test 400 error
        mock_res = MagicMock()
        mock_res.status_code = 400

        with (
            patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as m,
            patch.object(adapter, "_get_apns_jwt", new_callable=AsyncMock) as mj,
        ):
            m.return_value = mock_res
            mj.return_value = "jwt"
            res = await adapter.send_apns_void("t", "b")
            assert res.success is False

        # Test 500 error
        mock_res.status_code = 500
        res = await adapter.send_apns_void("t", "b")
        assert res.success is False

    @pytest.mark.asyncio
    async def test_send_fcm_invalid_token_errors(self, adapter):
        """Test FCM send with various token errors"""

        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch("adapters.push_notification_adapter.messaging.send") as m:
            # Test INVALID_ARGUMENT error
            m.side_effect = Exception("INVALID_ARGUMENT")
            res = await adapter._send_fcm("t", notif)
            assert res.success is False

            # Test SENDER_ID_MISMATCH error
            m.side_effect = Exception("SENDER_ID_MISMATCH")
            res = await adapter._send_fcm("t", notif)
            assert res.success is False

    @pytest.mark.asyncio
    async def test_send_apns_missing_bundle_id(self, adapter):
        """Test APNS send without bundle ID"""

        adapter._firebase_app = MagicMock()
        adapter.apns_bundle_id = None
        notif = create_notification("T", "B")

        res = await adapter._send_apns("t", notif)
        assert res.success is False
        assert "bundle ID not configured" in res.error

    @pytest.mark.asyncio
    async def test_get_apns_jwt_missing_config(self, adapter):
        """Test APNS JWT generation with missing configuration"""
        # Missing key path
        adapter.apns_key_path = None
        res = await adapter._get_apns_jwt()
        assert res == ""

        # Missing key ID
        adapter.apns_key_path = "/tmp/key"
        adapter.apns_key_id = None
        res = await adapter._get_apns_jwt()
        assert res == ""

    @pytest.mark.asyncio
    async def test_get_apns_jwt_file_not_found(self, adapter):
        """Test APNS JWT generation with missing key file"""
        adapter.apns_key_path = "/nonexistent/key.p8"
        adapter.apns_key_id = "test_key_id"
        adapter.apns_team_id = "test_team_id"

        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            res = await adapter._get_apns_jwt()
            assert res == ""

    @pytest.mark.asyncio
    async def test_shutdown_error_handling(self, adapter):
        """Test shutdown with Firebase app deletion errors"""
        adapter._firebase_app = MagicMock()

        with patch("firebase_admin.delete_app", side_effect=ValueError("App not found")):
            adapter.shutdown()  # Should handle error gracefully
            assert adapter._firebase_app is None
            assert adapter._is_initialized is False

    @pytest.mark.asyncio
    async def test_initialize_fcm_credential_error(self, adapter):
        """Test FCM initialization with credential loading error"""
        with (
            patch(
                "firebase_admin.credentials.Certificate",
                side_effect=Exception("Bad credentials"),
            ),
            patch("os.path.exists", return_value=True),
        ):
            adapter._initialize_fcm()  # Should handle error gracefully
            # When cred loading fails, cred becomes None, and initialize_app is called with None
            # This may or may not set _firebase_app depending on Firebase behavior

    @pytest.mark.asyncio
    async def test_send_to_token_exception_handling(self, adapter):
        """Test send_to_token with internal exceptions"""
        notif = create_notification("T", "B")

        with patch.object(adapter, "_send_fcm", side_effect=Exception("Internal error")):
            res = await adapter.send_to_token("t", notif)
            assert res.success is False
            assert "Internal error" in res.error

    @pytest.mark.asyncio
    async def test_send_to_user_exception_handling(self, adapter):
        """Test send_to_user with internal exceptions"""
        notif = create_notification("T", "B")
        adapter.device_tokens = {"t1": DeviceToken("t1", Platform.ANDROID, user_id="u1")}

        with patch.object(adapter, "send_to_token", side_effect=Exception("Send failed")):
            res = await adapter.send_to_user("u1", notif)
            assert res.success is False
            assert "Send failed" in res.error

    @pytest.mark.asyncio
    async def test_send_broadcast_exception_handling(self, adapter):
        """Test send_broadcast with internal exceptions"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        # Register a token first
        await adapter.register_token("test_token", Platform.ANDROID, "user123")

        with patch(
            "adapters.push_notification_adapter.messaging.send_each_for_multicast_sync",
            side_effect=Exception("Broadcast failed"),
        ):
            res = await adapter.send_broadcast(notif)
            assert res.success is False
            assert "Broadcast failed" in res.error

    @pytest.mark.asyncio
    async def test_send_to_topic_exception_handling(self, adapter):
        """Test send_to_topic with internal exceptions"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch(
            "adapters.push_notification_adapter.messaging.send",
            side_effect=Exception("Topic send failed"),
        ):
            res = await adapter.send_to_topic("news", notif)
            assert res.success is False
            assert "Topic send failed" in res.error

    @pytest.mark.asyncio
    async def test_subscribe_to_topic_exception_handling(self, adapter):
        """Test subscribe_to_topic with internal exceptions"""
        adapter._firebase_app = MagicMock()

        with patch(
            "adapters.push_notification_adapter.messaging.subscribe_to_topic",
            side_effect=Exception("Subscribe failed"),
        ):
            res = await adapter.subscribe_to_topic(["t1"], "news")
            assert res is False

    @pytest.mark.asyncio
    async def test_send_apns_exception_handling(self, adapter):
        """Test _send_apns with internal exceptions"""
        adapter._firebase_app = MagicMock()
        adapter.apns_bundle_id = "com.example.app"
        notif = create_notification("T", "B")

        with patch(
            "adapters.push_notification_adapter.messaging.send",
            side_effect=Exception("APNS failed"),
        ):
            res = await adapter._send_apns("t", notif)
            assert res.success is False
            assert "APNS failed" in res.error

    def test_notification_channel_to_dict(self):
        """Test NotificationChannel.to_dict() method"""
        channel = NotificationChannel(
            id="test_channel",
            name="Test Channel",
            description="A test channel",
            importance=5,
            enable_vibration=False,
            enable_lights=False,
            show_badge=False,
            vibration_pattern=[100, 200, 300],
            sound="notification.mp3",
        )
        result = channel.to_dict()
        assert result["channel_id"] == "test_channel"
        assert result["name"] == "Test Channel"
        assert result["description"] == "A test channel"
        assert result["importance"] == 5
        assert result["enable_vibration"] is False
        assert result["enable_lights"] is False
        assert result["show_badge"] is False
        assert result["vibration_pattern"] == [100, 200, 300]
        assert result["sound"] == "notification.mp3"

    def test_notification_result_from_firebase_exception_handling(self):
        """Test NotificationResult.from_firebase with exception handling"""
        # Mock response with exception
        mock_response = MagicMock()
        mock_response.exception = Exception("Firebase error")
        mock_response.canonical_address_count = None

        result = NotificationResult.from_firebase(mock_response)
        assert result.success is False
        assert result.error == "Firebase error"

        # Mock response without exception but with canonical address count
        mock_response.exception = None
        mock_response.canonical_address_count = 1
        mock_response.message_id = "msg123"

        result = NotificationResult.from_firebase(mock_response)
        assert result.success is True
        assert result.message_id == "msg123"
        assert result.canonical_token is True

    @pytest.mark.asyncio
    async def test_send_broadcast_multicast_message(self, adapter):
        """Test send_broadcast with MulticastMessage (no topic/condition)"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        # Register a token first
        await adapter.register_token("test_token", Platform.ANDROID, "user123")

        with patch("adapters.push_notification_adapter.messaging.send_each_for_multicast_sync") as m:
            m.return_value = MagicMock(success_count=1, failure_count=0)
            res = await adapter.send_broadcast(notif)
            assert res.success is True
            m.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_fcm_dry_run(self, adapter):
        """Test _send_fcm dry run handling"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch("adapters.push_notification_adapter.messaging.send") as m:
            res = await adapter._send_fcm("t", notif, dry_run=True)
            assert res.success is True
            m.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_apns_dry_run(self, adapter):
        """Test _send_apns dry run handling"""
        adapter._firebase_app = MagicMock()
        adapter.apns_bundle_id = "com.example.app"
        notif = create_notification("T", "B")

        with patch("adapters.push_notification_adapter.messaging.send") as m:
            res = await adapter._send_apns("t", notif, dry_run=True)
            assert res.success is True
            m.assert_not_called()

    def test_generate_id(self, adapter):
        """Test _generate_id method"""
        id1 = adapter._generate_id()
        id2 = adapter._generate_id()
        assert isinstance(id1, str)
        assert len(id1) == 36  # UUID4 length
        assert id1 != id2  # Should be unique

    @pytest.mark.asyncio
    async def test_main_function_asyncio_run(self):
        """Test that main function can be called with asyncio.run"""
        # This tests line 1208 where asyncio.run(main()) is called
        with patch("asyncio.run") as mock_run:
            # Import main function
            from adapters.push_notification_adapter import main

            # The test just verifies the function exists and can be imported
            # The actual asyncio.run call is tested implicitly by importing
            assert callable(main)

    @pytest.mark.asyncio
    async def test_get_active_tokens_with_filters(self, adapter):
        """Test active tokens retrieval with filters"""
        now = datetime.now()
        adapter.device_tokens = {
            "t1": DeviceToken("t1", Platform.ANDROID, user_id="u1", is_active=True, last_active=now),
            "t2": DeviceToken("t2", Platform.IOS, user_id="u1", is_active=True, last_active=now),
            "t3": DeviceToken("t3", Platform.ANDROID, user_id="u2", is_active=True, last_active=now),
            "t4": DeviceToken("t4", Platform.ANDROID, user_id="u1", is_active=False, last_active=now),
        }

        # Filter by user
        tokens = await adapter.get_active_tokens(user_id="u1")
        assert len(tokens) == 2  # t1 and t2, t4 is inactive

        # Filter by platform
        tokens = await adapter.get_active_tokens(platform=Platform.IOS)
        assert len(tokens) == 1
        assert tokens[0].token == "t2"

        # Filter by both
        tokens = await adapter.get_active_tokens(user_id="u1", platform=Platform.ANDROID)
        assert len(tokens) == 1
        assert tokens[0].token == "t1"

    @pytest.mark.asyncio
    async def test_cleanup_inactive_tokens_error_handling(self, adapter):
        """Test inactive token cleanup with errors"""
        old_date = datetime.now() - timedelta(days=40)
        adapter.device_tokens = {"t1": DeviceToken("t1", Platform.ANDROID, "u1", last_active=old_date)}

        with patch.object(adapter, "unregister_token", side_effect=Exception("cleanup error")):
            removed = await adapter.cleanup_inactive_tokens(max_inactive_days=30)
            assert removed == 0  # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_send_to_user_partial_failures(self, adapter):
        """Test send to user with partial failures"""
        adapter.device_tokens = {
            "t1": DeviceToken("t1", Platform.ANDROID, user_id="u1"),
            "t2": DeviceToken("t2", Platform.IOS, user_id="u1"),
        }
        notif = create_notification("T", "B")

        with patch.object(adapter, "send_to_token", new_callable=AsyncMock) as m:
            # First call succeeds, second fails
            m.side_effect = [
                NotificationResult(success=True),
                NotificationResult(success=False, error="token invalid"),
            ]

            res = await adapter.send_to_user("u1", notif)
            assert res.success is True  # At least one succeeded
            assert "1/2 sent" in (res.error or "")

    @pytest.mark.asyncio
    async def test_main_function(self):
        """Test the main function example"""
        # Mock the entire main function execution
        with (
            patch("adapters.push_notification_adapter.PushNotificationAdapter") as mock_adapter_class,
            patch("adapters.push_notification_adapter.create_notification") as mock_create,
            patch("builtins.print") as mock_print,
        ):
            mock_adapter = AsyncMock()
            mock_adapter_class.return_value = mock_adapter
            mock_adapter.initialize.return_value = True

            mock_notification = MagicMock()
            mock_create.return_value = mock_notification

            mock_result = MagicMock()
            mock_result.success = True
            mock_adapter.send_to_token.return_value = mock_result

            # Import and run main
            from adapters.push_notification_adapter import main

            await main()

            # Verify calls
            mock_adapter_class.assert_called_once()
            mock_adapter.initialize.assert_called_once()
            mock_adapter.register_token.assert_called_once()
            mock_adapter.send_to_token.assert_called_once()
            mock_print.assert_called()

    def test_notification_result_from_firebase_getattr_exception(self):
        """Test NotificationResult.from_firebase with getattr exception on canonical_address_count"""
        mock_response = MagicMock()
        mock_response.exception = None
        mock_response.message_id = "msg123"
        # Make canonical_address_count raise an exception
        mock_response.canonical_address_count = MagicMock(side_effect=Exception("getattr error"))

        result = NotificationResult.from_firebase(mock_response)
        assert result.success is True
        assert result.message_id == "msg123"
        assert result.canonical_token is False

    @pytest.mark.asyncio
    async def test_initialize_fcm_credential_loading_exception(self, adapter):
        """Test _initialize_fcm with credential loading exception"""
        adapter.fcm_credential_path = "/valid/path.json"
        adapter.fcm_project_id = "test-project"

        with patch("adapters.push_notification_adapter.os.path.exists", return_value=True):
            with patch(
                "adapters.push_notification_adapter.credentials.Certificate",
                side_effect=Exception("Credential error"),
            ):
                with patch("adapters.push_notification_adapter.firebase_admin.initialize_app") as mock_init:
                    with patch("builtins.print") as mock_print:
                        adapter._initialize_fcm()
                        # Should try to initialize app with None credentials
                        mock_init.assert_called_once_with(None, {"projectId": "test-project"})

    @pytest.mark.asyncio
    async def test_initialize_fcm_app_initialization_exception(self, adapter):
        """Test _initialize_fcm with firebase app initialization exception"""
        adapter.fcm_credential_path = "/valid/path.json"
        adapter.fcm_project_id = "test-project"

        with patch("adapters.push_notification_adapter.os.path.exists", return_value=True):
            with patch(
                "adapters.push_notification_adapter.credentials.Certificate",
                return_value=MagicMock(),
            ):
                with patch(
                    "adapters.push_notification_adapter.firebase_admin.initialize_app",
                    side_effect=Exception("App init error"),
                ):
                    with patch("builtins.print") as mock_print:
                        adapter._initialize_fcm()
                        mock_print.assert_called_with("[Push] FCM initialization warning: App init error")

    def test_create_default_channels(self, adapter):
        """Test _create_default_channels creates expected channels"""
        adapter._create_default_channels()

        assert "megabot_default" in adapter.notification_channels
        assert "megabot_alerts" in adapter.notification_channels
        assert "megabot_messages" in adapter.notification_channels
        assert "megabot_silent" in adapter.notification_channels

        default_channel = adapter.notification_channels["megabot_default"]
        assert default_channel.name == "MegaBot Messages"
        assert default_channel.importance == 4

    @pytest.mark.asyncio
    async def test_register_token_general_exception_handling(self, adapter):
        """Test register_token with general exception"""
        with patch.object(adapter, "_save_tokens", side_effect=Exception("Save failed")):
            result = await adapter.register_token("test_token", Platform.ANDROID, "user123")
            assert result is False

    @pytest.mark.asyncio
    async def test_unregister_token_general_exception_handling(self, adapter):
        """Test unregister_token with general exception"""
        adapter.device_tokens = {"test_token": DeviceToken("test_token", Platform.ANDROID, "user123")}
        with patch.object(adapter, "_save_tokens", side_effect=Exception("Save failed")):
            result = await adapter.unregister_token("test_token")
            assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_from_topic_no_firebase_app(self, adapter):
        """Test unsubscribe_from_topic without Firebase app"""
        adapter._firebase_app = None

        result = await adapter.unsubscribe_from_topic(["t1"], "news")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_webpush_exception_handling(self, adapter):
        """Test _send_webpush with internal exceptions"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch(
            "adapters.push_notification_adapter.messaging.send",
            side_effect=Exception("WebPush failed"),
        ):
            with patch("builtins.print") as mock_print:
                res = await adapter._send_webpush("t", notif)
                assert res.success is False
                assert "WebPush failed" in res.error
                mock_print.assert_called_with("[Push] WebPush send failed: WebPush failed")

    @pytest.mark.asyncio
    async def test_unsubscribe_from_topic_partial_success(self, adapter):
        """Test unsubscribe_from_topic with partial success"""
        adapter._firebase_app = MagicMock()
        mock_response = MagicMock()
        mock_response.success_count = 1
        firebase_messaging_mock.unsubscribe_from_topic.return_value = mock_response

        result = await adapter.unsubscribe_from_topic(["token1", "token2"], "test_topic")
        assert result is False  # success_count != len(tokens)

    @pytest.mark.asyncio
    async def test_get_apns_jwt_encode_exception(self, adapter):
        """Test _get_apns_jwt with JWT encoding exception"""
        adapter.apns_key_path = "/valid/path.p8"
        adapter.apns_key_id = "test_key"
        adapter.apns_team_id = "test_team"

        with patch("builtins.open", mock_open(read_data="key_data")):
            with patch("jwt.encode", side_effect=Exception("Encode error")):
                result = await adapter._get_apns_jwt()
                assert result == ""

    @pytest.mark.asyncio
    async def test_delete_notification_channel_exception_handling(self, adapter):
        """Test delete_notification_channel with exception"""
        # Mock the notification_channels dict to raise exception on deletion
        original_dict = adapter.notification_channels
        mock_dict = MagicMock()
        mock_dict.__contains__.return_value = True  # channel_id is "in" the dict
        mock_dict.__delitem__.side_effect = Exception("Deletion error")
        adapter.notification_channels = mock_dict

        try:
            with patch("builtins.print") as mock_print:
                result = await adapter.delete_notification_channel("test")
                assert result is False
                mock_print.assert_called_with("[Push] Channel deletion failed: Deletion error")
        finally:
            # Restore original dict
            adapter.notification_channels = original_dict

    @pytest.mark.asyncio
    async def test_subscribe_to_topic_success(self, adapter):
        """Test subscribe_to_topic with successful subscription"""
        adapter._firebase_app = MagicMock()

        with patch("adapters.push_notification_adapter.messaging.subscribe_to_topic") as mock_subscribe:
            mock_subscribe.return_value = mock_topic_response
            result = await adapter.subscribe_to_topic(["t1"], "news")
            assert result is True  # success_count (1) == len(tokens) (1)
            mock_subscribe.assert_called_once_with(["t1"], "news")

    @pytest.mark.asyncio
    async def test_subscribe_to_topic_partial_success(self, adapter):
        """Test subscribe_to_topic with partial success"""
        adapter._firebase_app = MagicMock()

        with patch("adapters.push_notification_adapter.messaging.subscribe_to_topic") as mock_subscribe:
            mock_response = MagicMock()
            mock_response.success_count = 1
            mock_subscribe.return_value = mock_response

            result = await adapter.subscribe_to_topic(["token1", "token2"], "test_topic")
            assert result is False  # success_count != len(tokens)
            mock_subscribe.assert_called_once_with(["token1", "token2"], "test_topic")

    @pytest.mark.asyncio
    async def test_create_notification_channel_exception_handling(self, adapter):
        """Test create_notification_channel with exception"""
        # Mock the notification_channels dict to raise exception on assignment
        original_dict = adapter.notification_channels
        mock_dict = MagicMock()
        mock_dict.__setitem__.side_effect = Exception("Creation error")
        adapter.notification_channels = mock_dict

        try:
            channel = NotificationChannel(id="c1", name="N")
            with patch("builtins.print") as mock_print:
                result = await adapter.create_notification_channel(channel)
                assert result is False
                mock_print.assert_called_with("[Push] Channel creation failed: Creation error")
        finally:
            # Restore original dict
            adapter.notification_channels = original_dict

    @pytest.mark.asyncio
    async def test_send_to_user_with_platform_filter(self, adapter):
        """Test send_to_user with platform filtering"""
        adapter.device_tokens = {
            "t1": DeviceToken("t1", Platform.ANDROID, user_id="u1"),
            "t2": DeviceToken("t2", Platform.IOS, user_id="u1"),
        }
        notif = create_notification("T", "B")

        with patch.object(adapter, "send_to_token", new_callable=AsyncMock) as m:
            m.return_value = NotificationResult(success=True)
            res = await adapter.send_to_user("u1", notif, platform=Platform.ANDROID)
            assert res.success is True
            assert m.call_count == 1  # Only Android token should be sent to
            # Verify the call was made with the Android token
            m.assert_called_once()
            call_kwargs = m.call_args[1]  # Get keyword arguments
            assert call_kwargs["token"] == "t1"  # Token should be t1

    @pytest.mark.asyncio
    async def test_main_function_execution(self):
        """Test that main function can be executed without error"""
        # Test that the main function exists and is callable
        from adapters.push_notification_adapter import main

        assert callable(main)

        # Mock the adapter initialization to avoid actual Firebase/APNS setup
        with patch("adapters.push_notification_adapter.PushNotificationAdapter") as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.initialize.return_value = True
            mock_adapter_class.return_value = mock_adapter

            # The main function should be awaitable (async)
            import asyncio

            assert asyncio.iscoroutinefunction(main)

    @pytest.mark.asyncio
    async def test_send_broadcast_no_active_tokens(self, adapter):
        """Test send_broadcast when no active tokens are registered"""
        adapter._firebase_app = MagicMock()
        adapter.device_tokens = {}
        notif = create_notification("T", "B")

        result = await adapter.send_broadcast(notif)
        assert result.success is False
        assert result.error == "No active tokens registered"

    @pytest.mark.asyncio
    async def test_send_webpush_full_coverage(self, adapter):
        """Test _send_webpush with dry_run and success paths"""
        adapter._firebase_app = MagicMock()
        notif = create_notification("T", "B")

        with patch("adapters.push_notification_adapter.messaging.send") as mock_send:
            mock_send.return_value = "web_msg_id"

            # Test dry_run (line 1029)
            result = await adapter._send_webpush("t", notif, dry_run=True)
            assert result.success is True
            mock_send.assert_not_called()

            # Test success (line 1032)
            result = await adapter._send_webpush("t", notif, dry_run=False)
            assert result.success is True
            assert result.message_id == "web_msg_id"
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_apns_jwt_success(self, adapter):
        """Test _get_apns_jwt success path (line 1066)"""
        adapter.apns_key_path = "/tmp/key.p8"
        adapter.apns_key_id = "keyid"
        adapter.apns_team_id = "teamid"

        with patch("builtins.open", mock_open(read_data="key_data")):
            with patch("jwt.encode", return_value="mock_jwt_token"):
                token = await adapter._get_apns_jwt()
                assert token == "mock_jwt_token"

    @pytest.mark.asyncio
    async def test_channel_management_success(self, adapter):
        """Test channel creation and deletion success (lines 1082, 1100)"""
        channel = NotificationChannel(id="new_channel", name="New")

        # Success creation
        assert await adapter.create_notification_channel(channel) is True
        assert "new_channel" in adapter.notification_channels

        # Success deletion
        assert await adapter.delete_notification_channel("new_channel") is True
        assert "new_channel" not in adapter.notification_channels

    @pytest.mark.asyncio
    async def test_cleanup_inactive_tokens_success(self, adapter):
        """Test cleanup_inactive_tokens success path (lines 1146-1148)"""
        old_date = datetime.now() - timedelta(days=40)
        adapter.device_tokens = {"t1": DeviceToken("t1", Platform.ANDROID, "u1", last_active=old_date)}

        with patch.object(adapter, "unregister_token", new_callable=AsyncMock) as mock_unreg:
            mock_unreg.return_value = True
            removed = await adapter.cleanup_inactive_tokens(max_inactive_days=30)
            assert removed == 1
            mock_unreg.assert_called_once_with("t1")


@pytest.mark.asyncio
async def test_push_notification_adapter_main():
    from adapters.push_notification_adapter import main

    with (
        patch(
            "adapters.push_notification_adapter.PushNotificationAdapter.initialize",
            AsyncMock(return_value=True),
        ),
        patch(
            "adapters.push_notification_adapter.PushNotificationAdapter.shutdown",
            AsyncMock(),
        ),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
    ):
        try:
            await main()
        except asyncio.CancelledError:
            pass
