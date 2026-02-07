import pytest
import io
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType


@pytest.fixture
def adapter():
    a = WhatsAppAdapter(
        "whatsapp", MagicMock(), {"phone_number_id": "123", "access_token": "token"}
    )
    a.is_initialized = True
    a.session = MagicMock()
    return a


@pytest.mark.asyncio
async def test_whatsapp_webhook_media_branches(adapter):
    types = ["image", "video", "audio", "document", "location", "contacts"]
    for t in types:
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
                                        "type": t,
                                        t: {"id": "1", "body": "hi"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        if t == "location":
            data["entry"][0]["changes"][0]["value"]["messages"][0][t] = {
                "latitude": 1,
                "longitude": 2,
            }
        msg = await adapter.handle_webhook(data)
        assert msg is not None


@pytest.mark.asyncio
async def test_whatsapp_openclaw_media_send(adapter):
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc_med"}}
    res = await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE)
    assert res.id == "oc_med"

    # Error case
    adapter._openclaw.execute_tool.return_value = {"error": "fail"}
    assert (
        await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE)
        is None
    )


@pytest.mark.asyncio
async def test_whatsapp_direct_upload_media_success(adapter):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"id": "up_id"}
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.post.return_value = mock_resp

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", return_value=io.BytesIO(b"abc")),
    ):
        res = await adapter._upload_media("file.png", MessageType.IMAGE)
        assert res == "up_id"


@pytest.mark.asyncio
async def test_whatsapp_format_text(adapter):
    assert adapter._format_text("hi *bold*", markup=True) == "hi \\*bold\\*"
    assert adapter._format_text("hi", markup=False) == "hi"


@pytest.mark.asyncio
async def test_whatsapp_send_with_retry_exception(adapter):
    adapter.session.post.side_effect = Exception("Transient")
    with patch("asyncio.sleep", return_value=None):
        res = await adapter._send_with_retry({"p": 1})
        assert res is None
