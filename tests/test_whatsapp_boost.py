import pytest
import io
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType


@pytest.fixture
def adapter():
    server = MagicMock()
    server.openclaw = None
    a = WhatsAppAdapter("wa", server, {"access_token": "tk", "phone_number_id": "123"})
    a.is_initialized = True
    a.session = AsyncMock()
    return a


@pytest.mark.asyncio
async def test_whatsapp_init_openclaw_manual(adapter):
    # lines 59-77
    adapter.server.openclaw = None
    with patch("adapters.openclaw_adapter.OpenClawAdapter") as mock_oc:
        mock_oc.return_value.connect = AsyncMock()
        success = await adapter._init_openclaw()
        assert success
        assert adapter._use_openclaw


@pytest.mark.asyncio
async def test_whatsapp_send_media_direct(adapter):
    # lines 184-202
    adapter._use_openclaw = False
    adapter._upload_media = AsyncMock(return_value="med123")
    adapter._send_with_retry = AsyncMock(return_value={"messages": [{"id": "m1"}]})
    res = await adapter.send_media("c1", "p.png")
    assert res.id == "m1"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_extra(adapter):
    # lines 684-700
    base = {
        "entry": [
            {
                "changes": [
                    {"value": {"messages": [{"from": "u", "id": "m", "type": ""}]}}
                ]
            }
        ]
    }

    # Video
    base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "video"
    msg = await adapter.handle_webhook(base)
    assert msg.content == "[Video]"

    # Audio
    base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "audio"
    msg = await adapter.handle_webhook(base)
    assert msg.content == "[Audio]"

    # Document
    base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "document"
    base["entry"][0]["changes"][0]["value"]["messages"][0]["document"] = {
        "filename": "f.txt"
    }
    msg = await adapter.handle_webhook(base)
    assert "f.txt" in msg.content


@pytest.mark.asyncio
async def test_whatsapp_upload_media_fail(adapter):
    # line 856
    with patch("os.path.exists", return_value=True):
        with patch(
            "builtins.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"abc")
        ):
            adapter.session.post.return_value.__aenter__.return_value.status = 400
            adapter.session.post.return_value.__aenter__.return_value.text = AsyncMock(
                return_value="fail"
            )
            res = await adapter._upload_media("p.png", MessageType.IMAGE)
            assert res is None
