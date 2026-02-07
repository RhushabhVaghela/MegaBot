import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType


@pytest.fixture
def mock_server():
    server = MagicMock()
    server.openclaw = None
    return server


@pytest.fixture
def adapter(mock_server):
    return WhatsAppAdapter(
        "whatsapp", mock_server, {"phone_number_id": "123", "access_token": "token"}
    )


@pytest.mark.asyncio
async def test_whatsapp_init_and_initialize_openclaw_success(mock_server):
    config = {
        "phone_number_id": "123",
        "access_token": "token",
        "openclaw": {"host": "localhost", "port": 8080},
    }
    adapter = WhatsAppAdapter("whatsapp", mock_server, config)
    with patch("adapters.openclaw_adapter.OpenClawAdapter") as mock_oa_class:
        mock_oa = mock_oa_class.return_value
        mock_oa.connect = AsyncMock()
        success = await adapter.initialize()
        assert success
        assert adapter._use_openclaw


@pytest.mark.asyncio
async def test_whatsapp_initialize_openclaw_from_server(mock_server):
    mock_server.openclaw = AsyncMock()
    adapter = WhatsAppAdapter("whatsapp", mock_server, {})
    success = await adapter.initialize()
    assert success
    assert adapter._openclaw == mock_server.openclaw


@pytest.mark.asyncio
async def test_whatsapp_initialize_direct_api_success(mock_server):
    config = {"phone_number_id": "123", "access_token": "token"}
    adapter = WhatsAppAdapter("whatsapp", mock_server, config)
    with patch.object(adapter, "_init_openclaw", return_value=False):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__.return_value = mock_resp
        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            success = await adapter.initialize()
            assert success
            assert adapter.is_initialized


@pytest.mark.asyncio
async def test_whatsapp_init_openclaw_exception(mock_server):
    adapter = WhatsAppAdapter("whatsapp", mock_server, {})
    with patch(
        "adapters.openclaw_adapter.OpenClawAdapter", side_effect=Exception("Err")
    ):
        success = await adapter._init_openclaw()
        assert not success


@pytest.mark.asyncio
async def test_whatsapp_init_direct_api_fail(mock_server):
    adapter = WhatsAppAdapter("whatsapp", mock_server, {"phone_number_id": "123"})
    mock_resp = AsyncMock()
    mock_resp.status = 401
    mock_resp.__aenter__.return_value = mock_resp
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        success = await adapter._init_direct_api()
        assert not success


@pytest.mark.asyncio
async def test_whatsapp_notify_callbacks(adapter):
    cb1 = AsyncMock()
    cb2 = MagicMock(side_effect=Exception("Fail"))
    adapter.register_notification_callback(cb1)
    adapter.register_notification_callback(cb2)
    await adapter._notify_callbacks({"data": 1})
    assert cb1.called
    assert cb2.called


@pytest.mark.asyncio
async def test_whatsapp_send_text_retry_and_error(adapter):
    adapter.is_initialized = True
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp
    with patch("asyncio.sleep", return_value=None):
        msg = await adapter.send_text("chat1", "hi")
        assert msg is None


@pytest.mark.asyncio
async def test_whatsapp_send_text_openclaw(adapter):
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
    msg = await adapter.send_text("chat1", "hello")
    assert msg.id == "oc123"


@pytest.mark.asyncio
async def test_whatsapp_send_text_direct(adapter):
    adapter.is_initialized = True
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "wa123"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp
    msg = await adapter.send_text("chat1", "hello")
    assert msg.id == "wa123"


@pytest.mark.asyncio
async def test_whatsapp_send_media_openclaw(adapter):
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
    msg = await adapter.send_media("chat1", "path.png")
    assert msg.id == "oc123"


@pytest.mark.asyncio
async def test_whatsapp_send_location(adapter):
    adapter.is_initialized = True
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "loc123"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp
    msg = await adapter.send_location("chat1", 1.0, 2.0, address="Addr", name="Place")
    assert msg.id == "loc123"
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc_loc"}}
    msg = await adapter.send_location("chat1", 1.0, 2.0)
    assert msg.id == "oc_loc"


@pytest.mark.asyncio
async def test_whatsapp_send_contact(adapter):
    adapter.is_initialized = True
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "con123"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp
    msg = await adapter.send_contact("chat1", {"name": "John", "phone": "123"})
    assert msg.id == "con123"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook(adapter):
    data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "user1",
                                    "id": "m1",
                                    "timestamp": "12345",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.handle_webhook(data)
    assert msg.content == "hello"
    data["entry"][0]["changes"][0]["value"]["messages"][0] = {
        "from": "user1",
        "id": "m2",
        "type": "image",
        "image": {"id": "media1", "mime_type": "image/png"},
    }
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"url": "http://media-url"}
    mock_resp.read.return_value = b"bytes"
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.get.return_value = mock_resp
    msg = await adapter.handle_webhook(data)
    assert msg.message_type == MessageType.IMAGE


@pytest.mark.asyncio
async def test_whatsapp_upload_media_error_paths(adapter):
    adapter.session = AsyncMock()
    res = await adapter._upload_media("nonexistent.png", MessageType.IMAGE)
    assert res is None

    mock_resp = AsyncMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value="Error")
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", MagicMock()):
            # Mock FormData to avoid it trying to read from the mocked file
            with patch("aiohttp.FormData") as mock_form_data:
                # Return the mock instance itself when called
                mock_form = MagicMock()
                mock_form_data.return_value = mock_form
                res = await adapter._upload_media("file.png", MessageType.IMAGE)
                assert res is None


@pytest.mark.asyncio
async def test_whatsapp_shutdown_and_utils(adapter):
    adapter.session = AsyncMock()
    adapter._openclaw = MagicMock()
    await adapter.shutdown()
    assert adapter._normalize_phone("(123) 456-7890") == "+1234567890"
    assert adapter._map_media_type(MessageType.VIDEO) == "video"
    assert adapter._mime_to_message_type("audio/mp3") == MessageType.AUDIO
    assert adapter._get_mime_type("test.pdf", MessageType.DOCUMENT) == "application/pdf"


@pytest.mark.asyncio
async def test_whatsapp_send_via_openclaw_error(adapter):
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.side_effect = Exception("OC Fail")
    res = await adapter._send_via_openclaw("c1", "txt", "text")
    assert res is None


@pytest.mark.asyncio
async def test_whatsapp_send_media_via_openclaw_error(adapter):
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.side_effect = Exception("OC Fail")
    res = await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE)
    assert res is None
