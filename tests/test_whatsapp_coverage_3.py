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
async def test_whatsapp_remaining_branches(adapter):
    # send_location openclaw fail
    adapter._use_openclaw = True
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"error": "fail"}
    res = await adapter.send_location("c1", 0, 0)
    assert res.id.startswith("wa_")

    # send_contact direct fail
    adapter._use_openclaw = False
    adapter.session.post.return_value.__aenter__.return_value.status = 400
    with patch("asyncio.sleep", return_value=None):
        res = await adapter.send_contact("c1", {"name": "N"})
        assert res is None

    # handle_webhook various cases
    # 1. empty
    assert await adapter.handle_webhook({}) is None
    # 2. no messages
    assert (
        await adapter.handle_webhook({"entry": [{"changes": [{"value": {}}]}]}) is None
    )
    # 3. interactive button_reply
    data_btn = {
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
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {"title": "Yes", "id": "y1"},
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.handle_webhook(data_btn)
    assert msg.content == "Yes"
    # 4. list_reply
    data_list = {
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
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {"title": "Opt1", "id": "o1"},
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.handle_webhook(data_list)
    assert msg.content == "Opt1"

    # _upload_media various
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"a")),
    ):
        adapter.session.post.return_value.__aenter__.return_value.status = 200
        adapter.session.post.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"id": "up1"}
        )
        assert await adapter._upload_media("p.png", MessageType.IMAGE) == "up1"

        adapter.session.post.return_value.__aenter__.return_value.status = 401
        assert await adapter._upload_media("p.png", MessageType.IMAGE) is None

    # _detect_mime_type
    with patch("mimetypes.guess_type", return_value=(None, None)):
        assert adapter._detect_mime_type("p.png") == "application/octet-stream"

    # make_call
    assert await adapter.make_call("c1") is False

    # _get_contact_name
    assert adapter._get_contact_name("123") == "WhatsApp:123"
