import pytest
import asyncio
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.server import (
    MegaBotMessagingServer,
    PlatformMessage,
    MessageType,
    SecureWebSocket,
    MediaAttachment,
    PlatformAdapter,
)


class BreakLoop(BaseException):
    pass


@pytest.fixture
def server():
    return MegaBotMessagingServer(enable_encryption=True)


@pytest.mark.asyncio
async def test_secure_websocket_decrypt_error():
    ws = SecureWebSocket()
    encrypted = ws.encrypt("test")
    assert ws.decrypt(encrypted) == "test"
    assert ws.decrypt("invalid-encrypted-data") == "invalid-encrypted-data"


@pytest.mark.asyncio
async def test_platform_adapter_defaults():
    adapter = PlatformAdapter("test_platform", None)
    msg = await adapter.send_text("chat1", "hi")
    assert msg.content == "hi"
    assert await adapter.send_media("chat1", "path") is None
    assert await adapter.send_document("chat1", "path") is None
    assert await adapter.download_media("mid", "path") is None
    assert await adapter.make_call("chat1") is True


@pytest.mark.asyncio
async def test_server_send_message_logic(server):
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
async def test_server_send_message_continue(server):
    server.clients["c1"] = AsyncMock()
    with patch("adapters.messaging.server.list", return_value=["c1", "c2"]):
        msg = PlatformMessage(str(uuid.uuid4()), "p", "s", "sn", "c", content="hi")
        await server.send_message(msg)


@pytest.mark.asyncio
async def test_server_handle_client_logic(server):
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
async def test_server_handle_client_edge_cases(server):
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
async def test_server_handle_client_loop_error(server):
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("1.1.1.1", 1)
    mock_ws.__aiter__.side_effect = Exception("Iteration error")
    await server._handle_client(mock_ws)


@pytest.mark.asyncio
async def test_server_process_message_branches(server):
    msgs = [
        {"type": "message", "sender_id": "u1", "chat_id": "c1", "content": "hi"},
        {
            "type": "media_upload",
            "attachment": {
                "type": "image",
                "filename": "f.png",
                "mime_type": "img/png",
                "size": 10,
                "data": "YQ==",
            },
        },
        {"type": "platform_connect", "platform": "unknown"},
        {"type": "command", "command": "cmd", "args": []},
        {"type": "unknown"},
    ]
    with patch("aiofiles.open", return_value=AsyncMock()):
        for msg in msgs:
            await server._process_message("c1", json.dumps(msg))
    await server._process_message("c1", "invalid json")


@pytest.mark.asyncio
async def test_server_handle_platform_message_types(server):
    handler_non_coro = MagicMock()
    handler_coro = AsyncMock()
    server.register_handler(handler_non_coro)
    server.register_handler(handler_coro)
    data = {
        "sender_id": "u1",
        "chat_id": "c1",
        "content": "hi",
        "timestamp": "2023-01-01T00:00:00",
        "attachments": [
            {
                "type": "image",
                "filename": "f.png",
                "mime_type": "img/png",
                "size": 10,
                "data": "YQ==",
            }
        ],
    }
    with patch("aiofiles.open", return_value=AsyncMock()):
        await server._handle_platform_message(data)
    assert handler_non_coro.called
    assert handler_coro.called


@pytest.mark.asyncio
async def test_server_handle_platform_message_error(server):
    handler = MagicMock(side_effect=Exception("Handler error"))
    server.register_handler(handler)
    data = {"sender_id": "u1", "chat_id": "c1", "content": "hi"}
    await server._handle_platform_message(data)


@pytest.mark.asyncio
async def test_server_handle_platform_message_from_adapter(server):
    handler_non_coro = MagicMock(side_effect=Exception("Err"))
    handler_coro = AsyncMock()
    server.register_handler(handler_non_coro)
    server.register_handler(handler_coro)
    msg = PlatformMessage("1", "p", "s", "sn", "c", content="hi")
    await server._handle_platform_message_from_adapter(msg)
    assert handler_non_coro.called
    assert handler_coro.called


@pytest.mark.asyncio
async def test_server_platform_connect_branches(server):
    platforms = [
        {"platform": "telegram", "credentials": {"token": "t"}},
        {"platform": "whatsapp", "config": {}},
        {"platform": "imessage"},
        {"platform": "sms", "config": {}},
        {"platform": "signal", "credentials": {"phone_number": "123"}, "config": {}},
        {"platform": "discord", "credentials": {"token": "t"}},
        {"platform": "slack", "credentials": {"bot_token": "t"}},
    ]

    async def mock_init():
        pass

    server.on_connect = AsyncMock()
    with (
        patch("adapters.messaging.telegram.TelegramAdapter"),
        patch("adapters.messaging.whatsapp.WhatsAppAdapter"),
        patch("adapters.messaging.imessage.IMessageAdapter"),
        patch("adapters.messaging.sms.SMSAdapter"),
        patch("adapters.signal_adapter.SignalAdapter") as mock_signal,
        patch("adapters.discord_adapter.DiscordAdapter"),
        patch("adapters.slack_adapter.SlackAdapter"),
    ):
        mock_signal.return_value.initialize = mock_init
        for p in platforms:
            await server._handle_platform_connect(p)
            assert p["platform"] in server.platform_adapters
    assert server.on_connect.called


@pytest.mark.asyncio
async def test_server_initialization_methods(server):
    with patch("adapters.memu_adapter.MemUAdapter"):
        await server.initialize_memu()
    with patch("adapters.memu_adapter.MemUAdapter", side_effect=Exception("Err")):
        await server.initialize_memu()
    with patch("adapters.voice_adapter.VoiceAdapter"):
        await server.initialize_voice("sid", "token", "123")
    with patch("adapters.voice_adapter.VoiceAdapter", side_effect=Exception("Err")):
        await server.initialize_voice("sid", "token", "123")


@pytest.mark.asyncio
async def test_signal_platform_adapter_send_text(server):
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
async def test_server_start_mock(server):
    with patch("websockets.serve", return_value=AsyncMock()) as mock_serve:
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert mock_serve.called


def test_media_attachment_to_dict():
    att = MediaAttachment(MessageType.IMAGE, "f.png", "img/png", 10, b"abc")
    d = att.to_dict()
    assert d["filename"] == "f.png"


def test_generate_id(server):
    assert server._generate_id() is not None
