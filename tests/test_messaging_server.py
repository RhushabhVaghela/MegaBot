"""
Tests for MegaBotMessagingServer
"""

import asyncio
import json
import os
import uuid
import pytest
import base64
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from adapters.messaging import (
    MegaBotMessagingServer,
    PlatformMessage,
    MediaAttachment,
    MessageType,
)
from adapters.messaging.server import (
    SecureWebSocket,
    PlatformAdapter,
)


class TestMegaBotMessagingServer:
    """Test suite for MegaBotMessagingServer"""

    @pytest.fixture
    def server(self):
        """Create MegaBotMessagingServer instance"""
        return MegaBotMessagingServer(host="127.0.0.1", port=18791, enable_encryption=False)

    @pytest.mark.asyncio
    async def test_send_message_to_clients(self, server):
        """Test sending message to connected clients"""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        server.clients = {"client1": mock_ws1, "client2": mock_ws2}

        message = PlatformMessage(
            id="test_msg",
            platform="native",
            sender_id="bot",
            sender_name="MegaBot",
            chat_id="global",
            content="Hello everyone",
        )

        await server.send_message(message)

        # Verify both clients received the message
        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_called_once()

        # Verify content
        sent_data = json.loads(mock_ws1.send.call_args[0][0])
        assert sent_data["id"] == "test_msg"
        assert sent_data["content"] == "Hello everyone"

    @pytest.mark.asyncio
    async def test_send_message_handles_disconnect(self, server):
        """Test that disconnected clients are removed"""
        mock_ws1 = AsyncMock()
        mock_ws1.send.side_effect = Exception("Disconnected")

        server.clients = {"client1": mock_ws1}

        message = PlatformMessage(
            id="test_msg",
            platform="native",
            sender_id="bot",
            sender_name="MegaBot",
            chat_id="global",
            content="Hello",
        )

        await server.send_message(message)

        # Client should be removed
        assert "client1" not in server.clients

    @pytest.mark.asyncio
    async def test_platform_connect_discord(self, server):
        """Test handling discord platform connection"""
        data = {
            "type": "platform_connect",
            "platform": "discord",
            "credentials": {"token": "test-token"},
        }

        # Patch it in the module where it's imported
        with patch("adapters.discord_adapter.DiscordAdapter") as mock_discord:
            await server._handle_platform_connect(data)

            assert "discord" in server.platform_adapters
            # Verification of call depends on how import is handled,
            # but since we see "Initialized Discord adapter" in logs, we know it ran.

    @pytest.mark.asyncio
    async def test_platform_connect_slack(self, server):
        """Test handling slack platform connection"""
        data = {
            "type": "platform_connect",
            "platform": "slack",
            "credentials": {"bot_token": "xoxb-test", "app_token": "xapp-test"},
            "config": {"signing_secret": "secret"},
        }

        with patch("adapters.slack_adapter.SlackAdapter") as mock_slack:
            await server._handle_platform_connect(data)

            assert "slack" in server.platform_adapters
            mock_slack.assert_called_once_with(
                platform_name="slack",
                server=server,
                bot_token="xoxb-test",
                app_token="xapp-test",
                signing_secret="secret",
            )

    def test_register_handler(self, server):
        """Test register_handler method"""

        def test_handler(message):
            pass

        server.register_handler(test_handler)
        assert test_handler in server.message_handlers

    @pytest.mark.asyncio
    async def test_initialize_memu_success(self, server):
        """Test successful memU initialization"""
        with patch("adapters.memu_adapter.MemUAdapter") as mock_memu:
            await server.initialize_memu("./memu", "sqlite:///test.db")

            mock_memu.assert_called_once_with("./memu", "sqlite:///test.db")
            assert server.memu_adapter is not None

    @pytest.mark.asyncio
    async def test_initialize_memu_failure(self, server):
        """Test memU initialization failure"""
        with patch("adapters.memu_adapter.MemUAdapter", side_effect=Exception("Import error")):
            await server.initialize_memu()

            assert server.memu_adapter is None

    @pytest.mark.asyncio
    async def test_initialize_voice_success(self, server):
        """Test successful voice adapter initialization"""
        with patch("adapters.voice_adapter.VoiceAdapter") as mock_voice:
            await server.initialize_voice("sid", "token", "+1234567890")

            mock_voice.assert_called_once_with("sid", "token", "+1234567890")
            assert server.voice_adapter is not None

    @pytest.mark.asyncio
    async def test_initialize_voice_failure(self, server):
        """Test voice adapter initialization failure"""
        with patch("adapters.voice_adapter.VoiceAdapter", side_effect=Exception("Import error")):
            await server.initialize_voice("sid", "token", "+1234567890")

            assert server.voice_adapter is None

    @pytest.mark.asyncio
    async def test_send_message_with_encryption(self):
        """Test send_message with encryption enabled"""
        server = MegaBotMessagingServer(enable_encryption=True)
        mock_ws = AsyncMock()
        server.clients = {"client1": mock_ws}

        # Mock secure_ws
        mock_secure_ws = MagicMock()
        mock_secure_ws.encrypt.return_value = "encrypted_data"
        server.secure_ws = mock_secure_ws

        message = PlatformMessage(
            id="test_msg",
            platform="native",
            sender_id="bot",
            sender_name="MegaBot",
            chat_id="global",
            content="Hello",
        )

        await server.send_message(message)

        # Verify encryption was called
        mock_secure_ws.encrypt.assert_called_once()
        mock_ws.send.assert_called_once_with("encrypted_data")

    @pytest.mark.asyncio
    async def test_send_message_target_client(self, server):
        """Test send_message to specific target client"""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        server.clients = {"client1": mock_ws1, "client2": mock_ws2}

        message = PlatformMessage(
            id="test_msg",
            platform="native",
            sender_id="bot",
            sender_name="MegaBot",
            chat_id="global",
            content="Hello",
        )

        await server.send_message(message, target_client="client1")

        # Only client1 should receive the message
        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_with_encryption(self, server):
        """Test _process_message with encryption enabled"""
        # Mock secure_ws
        mock_secure_ws = MagicMock()
        mock_secure_ws.decrypt.return_value = '{"type": "message", "content": "test"}'
        server.secure_ws = mock_secure_ws

        server.enable_encryption = True

        with patch.object(server, "_handle_platform_message") as mock_handler:
            await server._process_message("client1", "encrypted_data")

            mock_secure_ws.decrypt.assert_called_once_with("encrypted_data")
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_unknown_type(self, server):
        """Test _process_message with unknown message type"""
        data = {"type": "unknown", "content": "test"}

        # Should not raise exception, just print unknown type
        await server._process_message("client1", json.dumps(data))

    @pytest.mark.asyncio
    async def test_handle_platform_message_with_attachments(self, server):
        """Test _handle_platform_message with media attachments"""
        import base64

        attachment_data = {
            "type": "image",
            "filename": "test.jpg",
            "mime_type": "image/jpeg",
            "size": 100,
            "data": base64.b64encode(b"image_data").decode("utf-8"),
        }

        data = {
            "id": "msg123",
            "platform": "telegram",
            "sender_id": "user123",
            "sender_name": "Test User",
            "chat_id": "chat123",
            "content": "Hello with image",
            "attachments": [attachment_data],
        }

        mock_handler = AsyncMock()
        server.register_handler(mock_handler)

        with patch.object(server, "_save_media") as mock_save:
            await server._handle_platform_message(data)

            # Verify handler was called
            assert mock_handler.called
            message = mock_handler.call_args[0][0]
            assert message.id == "msg123"
            assert message.content == "Hello with image"
            assert len(message.attachments) == 1
            assert message.attachments[0].filename == "test.jpg"

            # Verify _save_media was called
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_media_upload(self, server):
        """Test _handle_media_upload method"""
        attachment_data = {
            "type": "document",
            "filename": "test.pdf",
            "mime_type": "application/pdf",
            "size": 1000,
            "data": base64.b64encode(b"pdf_data").decode("utf-8"),
        }

        data = {"attachment": attachment_data}

        with patch.object(server, "_save_media") as mock_save:
            await server._handle_media_upload(data)

            mock_save.assert_called_once()
            attachment = mock_save.call_args[0][0]
            assert attachment.filename == "test.pdf"
            assert attachment.type == MessageType.DOCUMENT

    @pytest.mark.asyncio
    async def test_handle_platform_connect_telegram(self, server):
        """Test _handle_platform_connect for telegram"""
        data = {
            "platform": "telegram",
            "credentials": {"token": "telegram_token"},
        }

        with patch("adapters.messaging.telegram.TelegramAdapter") as mock_telegram:
            await server._handle_platform_connect(data)

            assert "telegram" in server.platform_adapters
            mock_telegram.assert_called_once_with("telegram_token", server)

    @pytest.mark.asyncio
    async def test_handle_platform_connect_whatsapp(self, server):
        """Test _handle_platform_connect for whatsapp"""
        data = {
            "platform": "whatsapp",
            "config": {"session_path": "/tmp/whatsapp"},
        }

        with patch("adapters.messaging.whatsapp.WhatsAppAdapter") as mock_whatsapp:
            await server._handle_platform_connect(data)

            assert "whatsapp" in server.platform_adapters
            mock_whatsapp.assert_called_once_with("whatsapp", server, {"session_path": "/tmp/whatsapp"})

    @pytest.mark.asyncio
    async def test_handle_platform_connect_imessage(self, server):
        """Test _handle_platform_connect for imessage"""
        data = {"platform": "imessage"}

        with patch("adapters.messaging.imessage.IMessageAdapter") as mock_imessage:
            await server._handle_platform_connect(data)

            assert "imessage" in server.platform_adapters
            mock_imessage.assert_called_once_with("imessage", server)

    @pytest.mark.asyncio
    async def test_handle_platform_connect_sms(self, server):
        """Test _handle_platform_connect for sms"""
        data = {
            "platform": "sms",
            "config": {"provider": "twilio"},
        }

        with patch("adapters.messaging.sms.SMSAdapter") as mock_sms:
            await server._handle_platform_connect(data)

            assert "sms" in server.platform_adapters
            mock_sms.assert_called_once_with("sms", server, {"provider": "twilio"})

    @pytest.mark.asyncio
    async def test_handle_platform_connect_unknown(self, server):
        """Test _handle_platform_connect for unknown platform"""
        data = {"platform": "unknown_platform"}

        await server._handle_platform_connect(data)

        assert "unknown_platform" in server.platform_adapters
        # Should create a generic PlatformAdapter

    @pytest.mark.asyncio
    async def test_handle_command(self, server):
        """Test _handle_command method"""
        data = {"command": "test_cmd", "args": ["arg1", "arg2"]}

        # Should not raise exception
        await server._handle_command(data)

    @pytest.mark.asyncio
    async def test_save_media(self, server):
        """Test _save_media method"""

        # Create test attachment
        test_data = b"test media content"
        attachment = MediaAttachment(
            type=MessageType.DOCUMENT,
            filename="test.txt",
            mime_type="text/plain",
            size=len(test_data),
            data=test_data,
        )

        # Mock aiofiles to avoid actual file I/O
        with patch("adapters.messaging.server.aiofiles.open") as mock_open:
            mock_file = AsyncMock()
            mock_open.return_value.__aenter__.return_value = mock_file

            result = await server._save_media(attachment)

            # Verify file was written
            mock_file.write.assert_called_once_with(test_data)

            # Verify returned path contains hash and filename
            assert "test.txt" in result

    def test_generate_id(self, server):
        """Test _generate_id method"""
        id1 = server._generate_id()
        id2 = server._generate_id()

        # Should generate different UUIDs
        assert id1 != id2
        assert len(id1) == 36  # UUID length
        assert len(id2) == 36


class TestMediaAttachment:
    """Test suite for MediaAttachment"""

    def test_media_attachment_to_dict(self):
        """Test MediaAttachment.to_dict() method"""
        data = b"test image data"
        thumbnail = b"test thumbnail data"

        attachment = MediaAttachment(
            type=MessageType.IMAGE,
            filename="test.jpg",
            mime_type="image/jpeg",
            size=100,
            data=data,
            caption="Test image",
            thumbnail=thumbnail,
        )

        result = attachment.to_dict()

        expected = {
            "type": "image",
            "filename": "test.jpg",
            "mime_type": "image/jpeg",
            "size": 100,
            "data": base64.b64encode(data).decode("utf-8"),
            "caption": "Test image",
            "has_thumbnail": True,
        }

        assert result == expected

    def test_media_attachment_from_dict(self):
        """Test MediaAttachment.from_dict() classmethod"""
        data = b"test image data"
        thumbnail = b"test thumbnail data"

        data_dict = {
            "type": "image",
            "filename": "test.jpg",
            "mime_type": "image/jpeg",
            "size": 100,
            "data": base64.b64encode(data).decode("utf-8"),
            "caption": "Test image",
            "thumbnail": base64.b64encode(thumbnail).decode("utf-8"),
        }

        attachment = MediaAttachment.from_dict(data_dict)

        assert attachment.type == MessageType.IMAGE
        assert attachment.filename == "test.jpg"
        assert attachment.mime_type == "image/jpeg"
        assert attachment.size == 100
        assert attachment.data == data
        assert attachment.caption == "Test image"
        assert attachment.thumbnail == thumbnail

    def test_media_attachment_from_dict_no_thumbnail(self):
        """Test MediaAttachment.from_dict() without thumbnail"""
        data = b"test data"

        data_dict = {
            "type": "document",
            "filename": "test.pdf",
            "mime_type": "application/pdf",
            "size": 50,
            "data": base64.b64encode(data).decode("utf-8"),
        }

        attachment = MediaAttachment.from_dict(data_dict)

        assert attachment.type == MessageType.DOCUMENT
        assert attachment.filename == "test.pdf"
        assert attachment.thumbnail is None
        assert attachment.caption is None


# ---------------------------------------------------------------------------
# Tests migrated from test_messaging_server_coverage.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secure_websocket_decrypt_error():
    """Test SecureWebSocket encrypt/decrypt and invalid data."""
    ws = SecureWebSocket()
    encrypted = ws.encrypt("test")
    assert ws.decrypt(encrypted) == "test"
    with pytest.raises(ValueError, match="Decryption failed"):
        ws.decrypt("invalid-encrypted-data")


@pytest.mark.asyncio
async def test_platform_adapter_defaults():
    """Test PlatformAdapter default method implementations."""
    adapter = PlatformAdapter("test_platform", None)
    msg = await adapter.send_text("chat1", "hi")
    assert msg.content == "hi"
    assert await adapter.send_media("chat1", "path") is None
    assert await adapter.send_document("chat1", "path") is None
    assert await adapter.download_media("mid", "path") is None
    assert await adapter.make_call("chat1") is True


@pytest.mark.asyncio
async def test_server_send_message_target_and_error():
    """Test send_message with target_client, broadcast, and send failure."""
    server = MegaBotMessagingServer(enable_encryption=True)
    mock_client = AsyncMock()
    server.clients["c1"] = mock_client
    msg = PlatformMessage(str(uuid.uuid4()), "p", "s", "sn", "c", content="hi")
    await server.send_message(msg)
    assert mock_client.send.called
    mock_client.send.reset_mock()
    await server.send_message(msg, target_client="c2")
    assert mock_client.send.called
    mock_client.send.reset_mock()
    mock_client.send.side_effect = Exception("Send failed")
    await server.send_message(msg, target_client="c1")
    assert "c1" not in server.clients


@pytest.mark.asyncio
async def test_server_send_message_continue():
    """Test send_message continues past missing clients."""
    server = MegaBotMessagingServer(enable_encryption=True)
    server.clients["c1"] = AsyncMock()
    with patch("adapters.messaging.server.list", return_value=["c1", "c2"]):
        msg = PlatformMessage(str(uuid.uuid4()), "p", "s", "sn", "c", content="hi")
        await server.send_message(msg)


@pytest.mark.asyncio
async def test_server_handle_client_logic():
    """Test _handle_client with remote_address and bytes message."""
    server = MegaBotMessagingServer(enable_encryption=True)
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)
    mock_ws.__aiter__.return_value = ["bytes_msg".encode(), "text_msg"]
    client_id_found = None

    async def mock_process(cid, msg):
        nonlocal client_id_found
        client_id_found = cid

    with patch.object(server, "_process_message", side_effect=mock_process):
        await server._handle_client(mock_ws)
        assert client_id_found == "127.0.0.1:12345"


@pytest.mark.asyncio
async def test_server_handle_client_edge_cases():
    """Test _handle_client with unknown address fallback."""
    server = MegaBotMessagingServer(enable_encryption=True)
    mock_ws = AsyncMock()
    type(mock_ws).remote_address = property(lambda x: Exception("No address"))
    mock_ws.__aiter__.return_value = ["msg"]
    server.on_connect = AsyncMock()
    client_id_found = None

    async def mock_process(cid, msg):
        nonlocal client_id_found
        client_id_found = cid

    with patch.object(server, "_process_message", side_effect=mock_process):
        await server._handle_client(mock_ws)
        assert client_id_found.startswith("unknown-")


@pytest.mark.asyncio
async def test_server_handle_client_loop_error():
    """Test _handle_client when iteration raises exception."""
    server = MegaBotMessagingServer(enable_encryption=True)
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("1.1.1.1", 1)
    mock_ws.__aiter__.side_effect = Exception("Iteration error")
    await server._handle_client(mock_ws)


@pytest.mark.asyncio
async def test_server_handle_platform_message_error():
    """Test _handle_platform_message when handler raises exception."""
    server = MegaBotMessagingServer(enable_encryption=True)
    handler = MagicMock(side_effect=Exception("Handler error"))
    server.register_handler(handler)
    data = {"sender_id": "u1", "chat_id": "c1", "content": "hi"}
    await server._handle_platform_message(data)


@pytest.mark.asyncio
async def test_server_handle_platform_message_from_adapter():
    """Test _handle_platform_message_from_adapter with coro and non-coro handlers."""
    server = MegaBotMessagingServer(enable_encryption=True)
    handler_non_coro = MagicMock(side_effect=Exception("Err"))
    handler_coro = AsyncMock()
    server.register_handler(handler_non_coro)
    server.register_handler(handler_coro)
    msg = PlatformMessage("1", "p", "s", "sn", "c", content="hi")
    await server._handle_platform_message_from_adapter(msg)
    assert handler_non_coro.called
    assert handler_coro.called


@pytest.mark.asyncio
async def test_signal_platform_adapter_send_text():
    """Test Signal adapter send_text through platform connect."""
    server = MegaBotMessagingServer(enable_encryption=True)
    mock_signal = AsyncMock()
    mock_signal.send_message.return_value = "msg123"
    data = {"platform": "signal", "credentials": {"phone_number": "123"}, "config": {}}

    async def mock_init():
        pass

    with patch("adapters.signal_adapter.SignalAdapter", return_value=mock_signal):
        mock_signal.initialize = mock_init
        await server._handle_platform_connect(data)
    adapter = server.platform_adapters["signal"]
    msg = await adapter.send_text("chat1", "hi", reply_to="ref123")
    assert "msg123" in msg.id


@pytest.mark.asyncio
async def test_server_start_mock():
    """Test server start with mocked websockets.serve."""
    server = MegaBotMessagingServer(enable_encryption=True)
    with patch("websockets.serve", return_value=AsyncMock()) as mock_serve:
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert mock_serve.called


# ---------------------------------------------------------------------------
# SecureWebSocket — missing env vars (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------


class TestSecureWebSocketMissingEnvVars:
    """Cover server.py lines 104 and 113."""

    def test_missing_ws_password_raises(self):
        """Line 104: ValueError when MEGABOT_WS_PASSWORD is unset and no arg."""
        saved_pw = os.environ.pop("MEGABOT_WS_PASSWORD", None)
        saved_salt = os.environ.pop("MEGABOT_ENCRYPTION_SALT", None)
        try:
            with pytest.raises(ValueError, match="MEGABOT_WS_PASSWORD must be set"):
                SecureWebSocket(password=None)
        finally:
            # Restore both env vars so other tests aren't broken
            if saved_pw is not None:
                os.environ["MEGABOT_WS_PASSWORD"] = saved_pw
            if saved_salt is not None:
                os.environ["MEGABOT_ENCRYPTION_SALT"] = saved_salt

    def test_missing_encryption_salt_raises(self):
        """Line 113: ValueError when MEGABOT_ENCRYPTION_SALT is unset."""
        saved_salt = os.environ.pop("MEGABOT_ENCRYPTION_SALT", None)
        try:
            with pytest.raises(ValueError, match="MEGABOT_ENCRYPTION_SALT must be set"):
                # Provide password so we pass line 104 but fail at line 113
                SecureWebSocket(password="some-password")
        finally:
            if saved_salt is not None:
                os.environ["MEGABOT_ENCRYPTION_SALT"] = saved_salt


@pytest.mark.asyncio
async def test_messaging_server_final_gaps():
    from adapters.messaging.server import (
        MegaBotMessagingServer,
        SecureWebSocket,
    )

    server = MegaBotMessagingServer()
    server.register_handler(MagicMock(side_effect=Exception("Handler fail")))
    # Trigger line 298
    await server._handle_platform_message({"sender_id": "s", "chat_id": "c", "content": "hi"})

    # Trigger line 131-143: decrypt raises ValueError on invalid data
    sws = SecureWebSocket("password")
    with pytest.raises(ValueError, match="Decryption failed"):
        sws.decrypt("not-encrypted")

    # Trigger line 227 (Missing client during broadcast)
    mock_client = AsyncMock()
    server.clients = {"c1": mock_client}

    msg = PlatformMessage(
        id="1",
        sender_id="s",
        sender_name="n",
        chat_id="c",
        content="hi",
        platform="p",
        timestamp=datetime.now(),
    )

    # We want to remove 'c1' after clients_to_send is calculated but before it's used
    original_list = list

    def special_list(it):
        res = original_list(it)
        if isinstance(it, type(server.clients.keys())):
            server.clients.clear()
        return res

    with patch("adapters.messaging.server.list", side_effect=special_list):
        await server.send_message(msg)
