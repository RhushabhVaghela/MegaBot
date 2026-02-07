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
    return a


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
async def test_whatsapp_send_text_direct(adapter):
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "real_wa_id"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    msg = await adapter.send_text("chat1", "hello")
    assert msg.id == "real_wa_id"


@pytest.mark.asyncio
async def test_whatsapp_send_location(adapter):
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "loc_id"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    msg = await adapter.send_location("chat1", 1.0, 2.0)
    assert msg.id == "loc_id"


@pytest.mark.asyncio
async def test_whatsapp_send_contact(adapter):
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"messages": [{"id": "con_id"}]}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    msg = await adapter.send_contact("chat1", {"name": "J", "phone": "1"})
    assert msg.id == "con_id"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_media(adapter):
    data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "u",
                                    "id": "m",
                                    "type": "image",
                                    "image": {"id": "med", "mime_type": "image/png"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    adapter.session = MagicMock()

    # 1. Get media URL
    mock_resp_url = AsyncMock()
    mock_resp_url.status = 200
    mock_resp_url.json.return_value = {"url": "http://med"}
    mock_resp_url.__aenter__.return_value = mock_resp_url

    # 2. Download media
    mock_resp_data = AsyncMock()
    mock_resp_data.status = 200
    mock_resp_data.read.return_value = b"bytes"
    mock_resp_data.__aenter__.return_value = mock_resp_data

    adapter.session.get.side_effect = [mock_resp_url, mock_resp_data]

    with patch("aiofiles.open", return_value=AsyncMock()):
        msg = await adapter.handle_webhook(data)
        assert msg.message_type == MessageType.IMAGE


@pytest.mark.asyncio
async def test_whatsapp_upload_media_hang_fix(adapter):
    adapter.session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"id": "up_id"}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    with patch("os.path.exists", return_value=True):
        with patch(
            "builtins.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"abc")
        ):
            res = await adapter._upload_media("file.png", MessageType.IMAGE)
            assert res == "up_id"


@pytest.mark.asyncio
async def test_whatsapp_shutdown_simple(adapter):
    adapter.session = MagicMock()
    adapter.session.close = AsyncMock()
    await adapter.shutdown()
    assert adapter.session.close.called


@pytest.mark.asyncio
async def test_whatsapp_send_with_retry_logic(adapter):
    adapter.session = MagicMock()
    mock_resp_fail = AsyncMock()
    mock_resp_fail.status = 500
    mock_resp_fail.__aenter__.return_value = mock_resp_fail

    mock_resp_ok = AsyncMock()
    mock_resp_ok.status = 200
    mock_resp_ok.json.return_value = {"ok": True}
    mock_resp_ok.__aenter__.return_value = mock_resp_ok

    adapter.session.post.side_effect = [mock_resp_fail, mock_resp_ok]

    with patch("asyncio.sleep", return_value=None):
        res = await adapter._send_with_retry({"p": 1})
        assert res == {"ok": True}
        assert adapter.session.post.call_count == 2
