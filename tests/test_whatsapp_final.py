import pytest
import io
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
    a = WhatsAppAdapter(
        "whatsapp", mock_server, {"phone_number_id": "123", "access_token": "token"}
    )
    a.is_initialized = True
    a.session = MagicMock()
    return a


@pytest.mark.asyncio
async def test_whatsapp_initialize_all_paths(mock_server):
    # OpenClaw success from server
    mock_server.openclaw = AsyncMock()
    a1 = WhatsAppAdapter("wa", mock_server, {})
    assert await a1.initialize()

    # OpenClaw success from config
    mock_server.openclaw = None
    with patch("adapters.openclaw_adapter.OpenClawAdapter") as mock_oa_class:
        mock_oa = mock_oa_class.return_value
        mock_oa.connect = AsyncMock()
        a2 = WhatsAppAdapter("wa", mock_server, {"openclaw": {"host": "h"}})
        assert await a2.initialize()

    # Direct API success
    with patch.object(WhatsAppAdapter, "_init_openclaw", return_value=False):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__.return_value = mock_resp
        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            a3 = WhatsAppAdapter("wa", mock_server, {"phone_number_id": "123"})
            assert await a3.initialize()


@pytest.mark.asyncio
async def test_whatsapp_send_text_various(adapter):
    # OpenClaw
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc1"}}
    msg = await adapter.send_text("c1", "hi")
    assert msg.id == "oc1"

    # Direct
    adapter._use_openclaw = False
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "wa1"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp
    msg = await adapter.send_text("c1", "hi")
    assert msg.id == "wa1"


@pytest.mark.asyncio
async def test_whatsapp_send_media_various(adapter):
    # OpenClaw
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc2"}}
    msg = await adapter.send_media("c1", "p.png")
    assert msg.id == "oc2"

    # Direct
    adapter._use_openclaw = False
    mock_resp_up = AsyncMock()
    mock_resp_up.status = 200
    mock_resp_up.json.return_value = {"id": "med1"}
    mock_resp_up.__aenter__.return_value = mock_resp_up

    mock_resp_msg = AsyncMock()
    mock_resp_msg.status = 200
    mock_resp_msg.json.return_value = {"messages": [{"id": "wa2"}]}
    mock_resp_msg.__aenter__.return_value = mock_resp_msg

    adapter.session.post.side_effect = [mock_resp_up, mock_resp_msg]
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", return_value=io.BytesIO(b"a")),
    ):
        msg = await adapter.send_media("c1", "p.png")
        assert msg.id == "wa2"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_full(adapter):
    # Text
    data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "u1",
                                    "id": "m1",
                                    "type": "text",
                                    "text": {"body": "hi"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.handle_webhook(data)
    assert msg.content == "hi"

    # Interactive
    data_int = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "u1",
                                    "id": "m1",
                                    "type": "interactive",
                                    "interactive": {"type": "button_reply"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    adapter.notification_callbacks = [AsyncMock()]
    assert await adapter.handle_webhook(data_int) is None
    assert adapter.notification_callbacks[0].called

    # Location
    data_loc = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "u1",
                                    "id": "m1",
                                    "type": "location",
                                    "location": {"latitude": 1, "longitude": 2},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.handle_webhook(data_loc)
    assert "Location" in msg.content


@pytest.mark.asyncio
async def test_whatsapp_send_with_retry_rate_limit(adapter):
    mock_resp_429 = AsyncMock()
    mock_resp_429.status = 429
    mock_resp_429.__aenter__.return_value = mock_resp_429
    mock_resp_ok = AsyncMock()
    mock_resp_ok.status = 200
    mock_resp_ok.json.return_value = {"ok": True}
    mock_resp_ok.__aenter__.return_value = mock_resp_ok
    adapter.session.post.side_effect = [mock_resp_429, mock_resp_ok]
    with patch("asyncio.sleep", return_value=None):
        res = await adapter._send_with_retry({"p": 1})
        assert res == {"ok": True}


@pytest.mark.asyncio
async def test_whatsapp_utils_and_branches(adapter):
    assert adapter._detect_mime_type("p.png") == "image/png"
    assert adapter._mime_to_message_type("video/mp4") == MessageType.VIDEO
    assert adapter._map_media_type(MessageType.STICKER) == "sticker"
    assert adapter._map_media_type(MessageType.TEXT) == "document"  # fallback

    await adapter.shutdown()
    assert adapter.session.close.called


@pytest.mark.asyncio
async def test_whatsapp_location_and_contact(adapter):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "id1"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    msg_loc = await adapter.send_location("c1", 0, 0)
    assert msg_loc.id == "id1"

    msg_con = await adapter.send_contact("c1", {"name": "N", "phone": "P"})
    assert msg_con.id == "id1"
