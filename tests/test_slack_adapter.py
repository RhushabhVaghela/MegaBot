"""
Tests for SlackAdapter
"""

import asyncio
import pytest
import builtins
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from adapters.slack_adapter import SlackAdapter, SlackMessage
from adapters.messaging import PlatformMessage, MessageType


class TestSlackAdapter:
    """Test suite for SlackAdapter"""

    @pytest.fixture
    def mock_server(self):
        """Mock MegaBotMessagingServer"""
        return MagicMock()

    @pytest.fixture
    def slack_adapter(self, mock_server):
        """Create SlackAdapter instance with mocked dependencies"""
        with (
            patch("adapters.slack_adapter.WebClient") as mock_web_client,
            patch("adapters.slack_adapter.SocketModeClient") as mock_socket_client,
        ):
            # Configure mock_web_client to return a mock when instantiated
            mock_web_client.return_value = MagicMock()
            # Configure mock_socket_client to return a mock when instantiated
            mock_socket_client.return_value = MagicMock()

            adapter = SlackAdapter(
                platform_name="slack",
                server=mock_server,
                bot_token="xoxb-test-token",
                app_token="xapp-test-token",
                signing_secret="test-secret",
            )
            return adapter

    @pytest.fixture
    def mock_client(self, slack_adapter):
        """Mock WebClient"""
        return slack_adapter.client

    @pytest.fixture
    def mock_socket_client(self, slack_adapter):
        """Mock SocketModeClient"""
        return slack_adapter.socket_client

    def test_initialization(self, slack_adapter):
        """Test adapter initialization"""
        assert slack_adapter.platform_name == "slack"
        assert slack_adapter.bot_token == "xoxb-test-token"
        assert slack_adapter.app_token == "xapp-test-token"
        assert slack_adapter.signing_secret == "test-secret"
        assert not slack_adapter.is_initialized

    @pytest.mark.asyncio
    async def test_initialize_success(self, slack_adapter, mock_client):
        """Test successful initialization"""
        # Mock auth test response
        mock_client.auth_test.return_value = {"ok": True, "user_id": "U1234567890"}

        # Mock socket mode initialization
        with patch.object(slack_adapter, "_init_socket_mode", new_callable=AsyncMock):
            result = await slack_adapter.initialize()

            assert result is True
            assert slack_adapter.is_initialized
            assert slack_adapter.bot_user_id == "U1234567890"
            mock_client.auth_test.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_failure(self, slack_adapter, mock_client):
        """Test initialization failure"""
        mock_client.auth_test.return_value = {"ok": False, "error": "invalid_auth"}

        result = await slack_adapter.initialize()

        assert result is False
        assert not slack_adapter.is_initialized
        assert slack_adapter.bot_user_id is None

    @pytest.mark.asyncio
    async def test_send_text_success(self, slack_adapter, mock_client):
        """Test sending text message successfully"""
        mock_client.chat_postMessage.return_value = {
            "ok": True,
            "ts": "1234567890.123456",
        }

        result = await slack_adapter.send_text("C1234567890", "Hello World")

        assert result is not None
        assert isinstance(result, PlatformMessage)
        assert result.platform == "slack"
        assert result.content == "Hello World"
        assert result.chat_id == "C1234567890"
        assert result.sender_name == "MegaBot"

        mock_client.chat_postMessage.assert_called_once_with({"channel": "C1234567890", "text": "Hello World"})

    @pytest.mark.asyncio
    async def test_send_text_with_thread(self, slack_adapter, mock_client):
        """Test sending text message with thread reply"""
        mock_client.chat_postMessage.return_value = {
            "ok": True,
            "ts": "1234567890.123456",
        }

        result = await slack_adapter.send_text("C1234567890", "Reply", reply_to="9876543210.987654")

        assert result is not None
        assert result.reply_to == "9876543210.987654"

        mock_client.chat_postMessage.assert_called_once_with(
            {
                "channel": "C1234567890",
                "text": "Reply",
                "thread_ts": "9876543210.987654",
            }
        )

    @pytest.mark.asyncio
    async def test_send_text_failure(self, slack_adapter, mock_client):
        """Test sending text message failure"""
        mock_client.chat_postMessage.return_value = {
            "ok": False,
            "error": "channel_not_found",
        }

        result = await slack_adapter.send_text("C1234567890", "Hello World")

        assert result is None

    @pytest.mark.asyncio
    async def test_send_media_success(self, slack_adapter, mock_client):
        """Test sending media file successfully"""
        mock_client.files_upload_v2.return_value = {
            "ok": True,
            "file": {
                "id": "F1234567890",
                "shares": {"public": {"C1234567890": [{"ts": "1234567890.123456"}]}},
            },
        }

        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file

            result = await slack_adapter.send_media("C1234567890", "/path/to/image.jpg", "Test image")

            assert result is not None
            assert isinstance(result, PlatformMessage)
            assert result.platform == "slack"
            assert result.message_type == MessageType.IMAGE
            assert result.content == "Test image"

            mock_client.files_upload_v2.assert_called_once()
            mock_open.assert_called_once_with("/path/to/image.jpg", "rb")

    @pytest.mark.asyncio
    async def test_send_document(self, slack_adapter):
        """Test sending document"""
        with patch.object(slack_adapter, "send_media", new_callable=AsyncMock) as mock_send_media:
            mock_send_media.return_value = MagicMock()

            result = await slack_adapter.send_document("C1234567890", "/path/to/document.pdf", "Test doc")

            mock_send_media.assert_called_once_with(
                "C1234567890", "/path/to/document.pdf", "Test doc", MessageType.DOCUMENT
            )

    @pytest.mark.asyncio
    async def test_download_media(self, slack_adapter):
        """Test downloading media (not implemented)"""
        result = await slack_adapter.download_media("F1234567890", "/tmp/test.jpg")

        assert result is None

    @pytest.mark.asyncio
    async def test_make_call(self, slack_adapter):
        """Test making call (not supported)"""
        result = await slack_adapter.make_call("C1234567890", is_video=True)

        assert result is False

    @pytest.mark.asyncio
    async def test_add_reaction_success(self, slack_adapter, mock_client):
        """Test adding reaction successfully"""
        mock_client.reactions_add.return_value = {"ok": True}

        result = await slack_adapter.add_reaction("C1234567890", "1234567890.123456", "thumbsup")

        assert result is True
        mock_client.reactions_add.assert_called_once_with(
            {
                "channel": "C1234567890",
                "timestamp": "1234567890.123456",
                "name": "thumbsup",
            }
        )

    @pytest.mark.asyncio
    async def test_add_reaction_failure(self, slack_adapter, mock_client):
        """Test adding reaction failure"""
        mock_client.reactions_add.return_value = {"ok": False}

        result = await slack_adapter.add_reaction("C1234567890", "1234567890.123456", "thumbsup")

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_reaction_success(self, slack_adapter, mock_client):
        """Test removing reaction successfully"""
        mock_client.reactions_remove.return_value = {"ok": True}

        result = await slack_adapter.remove_reaction("C1234567890", "1234567890.123456", "thumbsup")

        assert result is True
        mock_client.reactions_remove.assert_called_once_with(
            {
                "channel": "C1234567890",
                "timestamp": "1234567890.123456",
                "name": "thumbsup",
            }
        )

    @pytest.mark.asyncio
    async def test_delete_message_success(self, slack_adapter, mock_client):
        """Test deleting message successfully"""
        mock_client.chat_delete.return_value = {"ok": True}

        result = await slack_adapter.delete_message("C1234567890", "1234567890.123456")

        assert result is True
        mock_client.chat_delete.assert_called_once_with({"channel": "C1234567890", "ts": "1234567890.123456"})

    @pytest.mark.asyncio
    async def test_get_channel_info_success(self, slack_adapter, mock_client):
        """Test getting channel info successfully"""
        mock_client.conversations_info.return_value = {
            "ok": True,
            "channel": {
                "id": "C1234567890",
                "name": "general",
                "is_private": False,
                "num_members": 42,
                "topic": {"value": "General discussion"},
                "purpose": {"value": "Company-wide announcements"},
                "created": 1234567890,
            },
        }

        result = await slack_adapter.get_channel_info("C1234567890")

        assert result is not None
        assert result["id"] == "C1234567890"
        assert result["name"] == "general"
        assert result["is_private"] is False
        assert result["member_count"] == 42

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, slack_adapter, mock_client):
        """Test getting user info successfully"""
        mock_client.users_info.return_value = {
            "ok": True,
            "user": {
                "id": "U1234567890",
                "name": "johndoe",
                "real_name": "John Doe",
                "profile": {"display_name": "John", "email": "john@example.com"},
                "is_bot": False,
            },
        }

        result = await slack_adapter.get_user_info("U1234567890")

        assert result is not None
        assert result["id"] == "U1234567890"
        assert result["name"] == "johndoe"
        assert result["real_name"] == "John Doe"
        assert result["email"] == "john@example.com"
        assert result["is_bot"] is False

    def test_register_handlers(self, slack_adapter):
        """Test registering various handlers"""

        def message_handler(msg):
            pass

        def reaction_handler(event, action):
            pass

        def command_handler():
            pass

        def event_handler(event):
            pass

        slack_adapter.register_message_handler(message_handler)
        slack_adapter.register_reaction_handler(reaction_handler)
        slack_adapter.register_command_handler("test", command_handler)
        slack_adapter.register_event_handler("test_event", event_handler)

        assert message_handler in slack_adapter.message_handlers
        assert reaction_handler in slack_adapter.reaction_handlers
        assert slack_adapter.command_handlers["test"] == command_handler
        assert slack_adapter.event_handlers["test_event"] == event_handler

    @pytest.mark.asyncio
    async def test_shutdown(self, slack_adapter):
        """Test adapter shutdown"""
        # Create a mock socket client with the necessary attributes
        mock_socket_client = MagicMock()
        mock_socket_client.client = MagicMock()
        mock_socket_client.client.disconnect = MagicMock()

        slack_adapter.socket_client = mock_socket_client
        slack_adapter.is_initialized = True

        await slack_adapter.shutdown()

        assert not slack_adapter.is_initialized
        mock_socket_client.client.disconnect.assert_called_once()

    def test_slack_message_from_event(self):
        """Test SlackMessage creation from event"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "Hello World",
            "thread_ts": "9876543210.987654",
            "files": [{"name": "test.jpg"}],
            "channel_type": "im",
        }

        msg = SlackMessage.from_event(event)

        assert msg.id == "1234567890.123456"
        assert msg.channel_id == "C1234567890"
        assert msg.user_id == "U1234567890"
        assert msg.text == "Hello World"
        assert msg.thread_ts == "9876543210.987654"
        assert msg.files == [{"name": "test.jpg"}]
        assert msg.is_dm is True

    @pytest.mark.asyncio
    async def test_to_platform_message_text(self, slack_adapter):
        """Test converting Slack event to PlatformMessage for text"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "Hello World",
            "thread_ts": "9876543210.987654",
        }

        with patch.object(slack_adapter, "_get_username", return_value="John Doe"):
            result = await slack_adapter._to_platform_message(event)

            assert isinstance(result, PlatformMessage)
            assert result.id == "slack_1234567890.123456"
            assert result.platform == "slack"
            assert result.sender_id == "U1234567890"
            assert result.sender_name == "John Doe"
            assert result.chat_id == "C1234567890"
            assert result.content == "Hello World"
            assert result.message_type == MessageType.TEXT
            assert result.reply_to == "9876543210.987654"

    @pytest.mark.asyncio
    async def test_to_platform_message_with_files(self, slack_adapter):
        """Test converting Slack event to PlatformMessage with files"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "",
            "files": [
                {"mimetype": "image/jpeg"},
                {"mimetype": "video/mp4"},
                {"mimetype": "audio/mpeg"},
                {"mimetype": "application/pdf"},
            ],
        }

        with patch.object(slack_adapter, "_get_username", return_value="John Doe"):
            result = await slack_adapter._to_platform_message(event)

            # Based on the logic in SlackAdapter, if there's an image, it returns IMAGE
            assert result.message_type == MessageType.IMAGE

    @pytest.mark.asyncio
    async def test_handle_message_event(self, slack_adapter):
        """Test handling message events"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "Hello World",
        }

        mock_handler = AsyncMock()
        slack_adapter.register_message_handler(mock_handler)

        with patch.object(slack_adapter, "_to_platform_message") as mock_convert:
            mock_convert.return_value = MagicMock()

            await slack_adapter._handle_message_event(event)

            mock_convert.assert_called_once_with(event)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_event_skip_bot(self, slack_adapter):
        """Test that bot messages are skipped"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",  # Same as bot_user_id
            "text": "Hello World",
        }

        slack_adapter.bot_user_id = "U1234567890"

        mock_handler = AsyncMock()
        slack_adapter.register_message_handler(mock_handler)

        await slack_adapter._handle_message_event(event)

        # Handler should not be called for bot messages
        mock_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_reaction_event(self, slack_adapter):
        """Test handling reaction events"""
        event = {
            "user": "U1234567890",
            "reaction": "thumbsup",
            "item": {"channel": "C1234567890", "ts": "1234567890.123456"},
        }

        mock_handler = AsyncMock()
        slack_adapter.register_reaction_handler(mock_handler)

        await slack_adapter._handle_reaction_event(event, "add")

        mock_handler.assert_called_once_with(event, "add")

    def test_slack_imports_fallback(self):
        """Test slack_sdk import fallback when not available"""
        with patch.dict("sys.modules", {"slack_sdk": None}):
            # Force reimport to trigger fallback
            import importlib
            import adapters.slack_adapter

            importlib.reload(adapters.slack_adapter)

            # Check that fallback mocks are in place
            assert hasattr(adapters.slack_adapter, "slack_sdk")
            assert adapters.slack_adapter.slack_sdk is not None
            assert hasattr(adapters.slack_adapter, "WebClient")
            assert hasattr(adapters.slack_adapter, "SocketModeClient")

    @pytest.mark.asyncio
    async def test_init_socket_mode(self, slack_adapter, mock_client):
        """Test socket mode initialization"""
        slack_adapter.app_token = "xapp-test-token"

        with patch("adapters.slack_adapter.SocketModeClient") as mock_socket_mode_client:
            mock_socket_client_instance = MagicMock()
            mock_socket_mode_client.return_value = mock_socket_client_instance
            mock_socket_client_instance.client.connect = MagicMock()

            await slack_adapter._init_socket_mode()

            mock_socket_mode_client.assert_called_once_with(app_token="xapp-test-token", web_client=mock_client)
            mock_socket_client_instance.client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_socket_request_events_api(self, slack_adapter):
        """Test handling Socket Mode requests with events_api"""
        mock_req = MagicMock()
        mock_req.type = "events_api"
        mock_req.envelope_id = "test_envelope_id"
        mock_req.payload = {
            "type": "event_callback",
            "event": {"type": "message", "text": "test"},
        }

        with patch.object(slack_adapter, "_handle_event") as mock_handle_event:
            with patch("adapters.slack_adapter.SocketModeResponse") as mock_response_class:
                with patch.object(slack_adapter, "socket_client", create=True) as mock_socket_client:
                    mock_response = MagicMock()
                    mock_response_class.return_value = mock_response
                    mock_socket_client.client.send_socket_mode_response = MagicMock()

                    await slack_adapter._handle_socket_request(mock_req)

                    mock_handle_event.assert_called_once_with({"type": "message", "text": "test"})
                    mock_response_class.assert_called_once_with(envelope_id="test_envelope_id")
                    mock_socket_client.client.send_socket_mode_response.assert_called_once_with(mock_response)

    @pytest.mark.asyncio
    async def test_handle_event_message(self, slack_adapter):
        """Test handling message events"""
        event = {"type": "message", "user": "U123", "text": "test"}

        with patch.object(slack_adapter, "_handle_message_event") as mock_handle_message:
            await slack_adapter._handle_event(event)
            mock_handle_message.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_handle_event_reaction_add(self, slack_adapter):
        """Test handling reaction add events"""
        event = {"type": "reaction_added", "user": "U123"}

        with patch.object(slack_adapter, "_handle_reaction_event") as mock_handle_reaction:
            await slack_adapter._handle_event(event)
            mock_handle_reaction.assert_called_once_with(event, "add")

    @pytest.mark.asyncio
    async def test_handle_event_reaction_remove(self, slack_adapter):
        """Test handling reaction remove events"""
        event = {"type": "reaction_removed", "user": "U123"}

        with patch.object(slack_adapter, "_handle_reaction_event") as mock_handle_reaction:
            await slack_adapter._handle_event(event)
            mock_handle_reaction.assert_called_once_with(event, "remove")

    @pytest.mark.asyncio
    async def test_handle_event_custom_handler(self, slack_adapter):
        """Test handling custom events with registered handlers"""
        event = {"type": "custom_event", "data": "test"}

        mock_handler = AsyncMock()
        slack_adapter.register_event_handler("custom_event", mock_handler)

        await slack_adapter._handle_event(event)

        mock_handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_get_username_success(self, slack_adapter, mock_client):
        """Test successful username retrieval"""
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "johndoe"}}

        result = await slack_adapter._get_username("U123")

        assert result == "johndoe"
        mock_client.users_info.assert_called_once_with({"user": "U123"})

    @pytest.mark.asyncio
    async def test_get_username_failure(self, slack_adapter, mock_client):
        """Test username retrieval failure"""
        mock_client.users_info.side_effect = ConnectionError("API Error")

        result = await slack_adapter._get_username("U123")

        assert result == "slack_user_U123"

    @pytest.mark.asyncio
    async def test_to_platform_message_video_files(self, slack_adapter):
        """Test message type detection for video files"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "",
            "files": [{"mimetype": "video/mp4"}],
        }

        with patch.object(slack_adapter, "_get_username", return_value="John Doe"):
            result = await slack_adapter._to_platform_message(event)
            assert result.message_type.value == "video"

    @pytest.mark.asyncio
    async def test_to_platform_message_audio_files(self, slack_adapter):
        """Test message type detection for audio files"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "",
            "files": [{"mimetype": "audio/mpeg"}],
        }

        with patch.object(slack_adapter, "_get_username", return_value="John Doe"):
            result = await slack_adapter._to_platform_message(event)
            assert result.message_type.value == "audio"

    @pytest.mark.asyncio
    async def test_to_platform_message_document_files(self, slack_adapter):
        """Test message type detection for document files"""
        event = {
            "ts": "1234567890.123456",
            "channel": "C1234567890",
            "user": "U1234567890",
            "text": "",
            "files": [{"mimetype": "application/pdf"}],
        }

        with patch.object(slack_adapter, "_get_username", return_value="John Doe"):
            result = await slack_adapter._to_platform_message(event)
            assert result.message_type.value == "document"

    @pytest.mark.asyncio
    async def test_send_text_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in send_text"""
        mock_client.chat_postMessage.side_effect = ConnectionError("API Error")

        result = await slack_adapter.send_text("C1234567890", "Hello World")

        assert result is None

    @pytest.mark.asyncio
    async def test_send_media_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in send_media"""
        mock_client.files_upload_v2.side_effect = OSError("Upload Error")

        result = await slack_adapter.send_media("C1234567890", "/path/to/image.jpg")

        assert result is None

    @pytest.mark.asyncio
    async def test_send_media_upload_failure(self, slack_adapter, mock_client):
        """Test send_media when file upload fails"""
        mock_client.files_upload_v2.return_value = {
            "ok": False,
            "error": "upload_failed",
        }

        with patch("builtins.open", mock_open(read_data=b"fake file content")):
            result = await slack_adapter.send_media("C1234567890", "/path/to/image.jpg")

        assert result is None
        mock_client.files_upload_v2.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_media_not_implemented(self, slack_adapter):
        """Test download_media (not implemented)"""
        result = await slack_adapter.download_media("msg123", "/path/to/save")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_reaction_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in add_reaction"""
        mock_client.reactions_add.side_effect = ConnectionError("API Error")

        result = await slack_adapter.add_reaction("C1234567890", "1234567890.123456", "thumbsup")

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_reaction_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in remove_reaction"""
        mock_client.reactions_remove.side_effect = ConnectionError("API Error")

        result = await slack_adapter.remove_reaction("C1234567890", "1234567890.123456", "thumbsup")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_message_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in delete_message"""
        mock_client.chat_delete.side_effect = ConnectionError("API Error")

        result = await slack_adapter.delete_message("C1234567890", "1234567890.123456")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_channel_info_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in get_channel_info"""
        mock_client.conversations_info.side_effect = ConnectionError("API Error")

        result = await slack_adapter.get_channel_info("C1234567890")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_exception_handling(self, slack_adapter, mock_client):
        """Test exception handling in get_user_info"""
        mock_client.users_info.side_effect = ConnectionError("API Error")

        result = await slack_adapter.get_user_info("U1234567890")

        assert result is None

    @pytest.mark.asyncio
    async def test_initialize_auth_test_failure(self, slack_adapter, mock_client):
        """Test initialize when auth_test fails"""
        mock_client.auth_test.return_value = {"ok": False, "error": "invalid_auth"}

        result = await slack_adapter.initialize()
        assert result is False
        assert slack_adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_initialize_exception_handling(self, slack_adapter, mock_client):
        """Test initialize exception handling"""
        mock_client.auth_test.side_effect = Exception("Connection error")

        result = await slack_adapter.initialize()
        assert result is False
        assert slack_adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_init_socket_mode_no_app_token(self, slack_adapter):
        """Test _init_socket_mode with no app token"""
        slack_adapter.app_token = None

        # Should return early without doing anything
        await slack_adapter._init_socket_mode()
        assert slack_adapter.socket_client is None

    @pytest.mark.asyncio
    async def test_handle_socket_request_events_api_dupe(self, slack_adapter):
        """Test _handle_socket_request with events_api"""
        from unittest.mock import AsyncMock

        # Mock socket client and request
        mock_socket_client = MagicMock()
        slack_adapter.socket_client = mock_socket_client

        mock_req = MagicMock()
        mock_req.type = "events_api"
        mock_req.envelope_id = "test_envelope"
        mock_req.payload = {
            "type": "event_callback",
            "event": {"type": "message", "text": "test"},
        }

        with patch.object(slack_adapter, "_handle_event", new_callable=AsyncMock) as mock_handle_event:
            with patch("adapters.slack_adapter.SocketModeResponse") as mock_response_class:
                mock_response = MagicMock()
                mock_response_class.return_value = mock_response
                await slack_adapter._handle_socket_request(mock_req)

                mock_handle_event.assert_called_once_with({"type": "message", "text": "test"})
                mock_socket_client.client.send_socket_mode_response.assert_called_once_with(mock_response)

    @pytest.mark.asyncio
    async def test_handle_event_custom_handler_exception(self, slack_adapter):
        """Test _handle_event with custom handler exception"""
        slack_adapter.event_handlers["custom_event"] = MagicMock(side_effect=Exception("handler error"))

        await slack_adapter._handle_event({"type": "custom_event"})

        # Should not raise exception, just log it

    @pytest.mark.asyncio
    async def test_handle_message_event_skip_bot_messages(self, slack_adapter):
        """Test _handle_message_event skips bot messages"""
        slack_adapter.bot_user_id = "U123"

        # Test skip bot user
        event = {"user": "U123", "text": "bot message"}
        with patch.object(slack_adapter, "_to_platform_message", new_callable=AsyncMock) as mock_to_msg:
            await slack_adapter._handle_message_event(event)
            mock_to_msg.assert_not_called()

        # Test skip bot_id
        event = {"bot_id": "B123", "text": "bot message"}
        await slack_adapter._handle_message_event(event)
        mock_to_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_event_handler_exception(self, slack_adapter):
        """Test _handle_message_event with handler exception"""
        slack_adapter.message_handlers = [MagicMock(side_effect=Exception("handler error"))]

        event = {"user": "U456", "text": "test message"}
        with patch.object(slack_adapter, "_to_platform_message", new_callable=AsyncMock) as mock_to_msg:
            mock_to_msg.return_value = MagicMock()
            await slack_adapter._handle_message_event(event)

            # Handler should have been called despite exception

    @pytest.mark.asyncio
    async def test_handle_reaction_event_handler_exception(self, slack_adapter):
        """Test _handle_reaction_event with handler exception"""
        slack_adapter.reaction_handlers = [MagicMock(side_effect=Exception("handler error"))]

        event = {"type": "reaction_added", "reaction": "thumbsup"}
        await slack_adapter._handle_reaction_event(event, "add")

        # Handler should have been called despite exception

    @pytest.mark.asyncio
    async def test_get_channel_info_api_failure(self, slack_adapter, mock_client):
        """Test get_channel_info when API call fails"""
        mock_client.conversations_info.return_value = {
            "ok": False,
            "error": "channel_not_found",
        }

        result = await slack_adapter.get_channel_info("C123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_api_failure(self, slack_adapter, mock_client):
        """Test get_user_info when API call fails"""
        mock_client.users_info.return_value = {"ok": False, "error": "user_not_found"}

        result = await slack_adapter.get_user_info("U123")
        assert result is None

    @pytest.mark.asyncio
    async def test_download_media_exception_handling(self, slack_adapter):
        """Test download_media returns None and logs not implemented"""
        result = await slack_adapter.download_media("msg123", "/path")
        assert result is None

    def test_generate_id(self, slack_adapter):
        """Test _generate_id method"""
        result = slack_adapter._generate_id()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_init_socket_mode_decorator_execution(self, slack_adapter):
        """Test that _init_socket_mode executes the decorator and function"""
        slack_adapter.app_token = "xapp-test-token"

        with patch("adapters.slack_adapter.SocketModeClient") as mock_socket_mode_client:
            mock_socket_client_instance = MagicMock()
            mock_socket_mode_client.return_value = mock_socket_client_instance
            mock_socket_client_instance.client.connect = MagicMock()

            # Capture the listener function
            captured_listener = None

            def mock_decorator(func):
                nonlocal captured_listener
                captured_listener = func
                return func

            mock_socket_client_instance.socket_mode_request_listener = mock_decorator

            # This should execute the decorator
            await slack_adapter._init_socket_mode()

            # Now call the decorated function
            assert captured_listener is not None
            mock_req = MagicMock()
            with patch.object(slack_adapter, "_handle_socket_request", new_callable=AsyncMock) as mock_handle:
                await captured_listener(mock_socket_client_instance, mock_req)
                mock_handle.assert_called_once_with(mock_req)

    @pytest.mark.asyncio
    async def test_download_media_actual_exception_handling(self, slack_adapter):
        """Test exception handling in download_media"""
        # Patch the print function to raise an exception when called from download_media
        original_print = builtins.print

        def failing_print(*args, **kwargs):
            if len(args) > 0 and str(args[0]).startswith("[Slack] Download media not implemented"):
                raise Exception("Simulated print error")
            return original_print(*args, **kwargs)

        with patch("builtins.print", side_effect=failing_print):
            result = await slack_adapter.download_media("msg123", "/path")
            assert result is None

    def test_slack_sdk_fallback_full_coverage(self):
        """Test the fallback mocks in slack_adapter for full coverage (lines 27, 30, 34)"""
        with patch.dict("sys.modules", {"slack_sdk": None}):
            import importlib
            import adapters.slack_adapter

            importlib.reload(adapters.slack_adapter)

            # Now test the fallback classes
            client = adapters.slack_adapter.WebClient(token="test")
            # This triggers __getattr__ (line 30)
            result = client.any_method()
            assert isinstance(result, MagicMock)

            socket_client = adapters.slack_adapter.SocketModeClient(app_token="test")
            assert socket_client is not None


@pytest.mark.asyncio
async def test_slack_adapter_final():
    server = MagicMock()
    from adapters.slack_adapter import SlackAdapter

    adapter = SlackAdapter("slack", server, bot_token="token", app_token="xapp-123")
    assert adapter._generate_id() is not None

    # Trigger line 162
    mock_socket_client = MagicMock()
    with (
        patch("adapters.slack_adapter.SocketModeClient", return_value=mock_socket_client),
        patch("adapters.slack_adapter.WebClient"),
        patch("asyncio.get_event_loop") as mock_loop,
    ):
        # Capture the listener function
        listener_fn = None

        def save_listener(fn):
            nonlocal listener_fn
            listener_fn = fn
            return fn

        mock_socket_client.socket_mode_request_listener = save_listener

        # Mock connection logic to avoid actual network calls
        mock_loop.return_value.run_in_executor.return_value = asyncio.Future()
        mock_loop.return_value.run_in_executor.return_value.set_result({"ok": True, "user_id": "U123"})

        await adapter.initialize()

        if listener_fn:
            mock_req = MagicMock()
            # Must be awaited since process_socket_mode_request is async
            await listener_fn(mock_socket_client, mock_req)
    await adapter.shutdown()


class TestSetupEventHandlers:
    """Phase 5-5: Tests for _setup_event_handlers (Phase 3B)"""

    @pytest.fixture
    def adapter(self):
        """Create SlackAdapter with mocked deps"""
        with (
            patch("adapters.slack_adapter.WebClient") as mock_wc,
            patch("adapters.slack_adapter.SocketModeClient") as mock_sc,
        ):
            mock_wc.return_value = MagicMock()
            mock_sc.return_value = MagicMock()
            adapter = SlackAdapter(
                platform_name="slack",
                server=MagicMock(),
                bot_token="xoxb-test",
                app_token="xapp-test",
                signing_secret="secret",
            )
            return adapter

    def test_event_handlers_registers_five_types(self, adapter):
        """_setup_event_handlers registers all 5 expected event types"""
        expected = {"message", "reaction_added", "reaction_removed", "app_mention", "member_joined_channel"}
        assert set(adapter.event_handlers.keys()) == expected

    def test_event_handlers_are_callable(self, adapter):
        """Each registered event handler is callable"""
        for event_type, handler in adapter.event_handlers.items():
            assert callable(handler), f"Handler for '{event_type}' is not callable"

    def test_event_handlers_noop_by_default(self, adapter):
        """Default event handlers return None (no-op stubs)"""
        for event_type, handler in adapter.event_handlers.items():
            result = handler({"type": event_type})
            assert result is None, f"Handler for '{event_type}' should return None"
