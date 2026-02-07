import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType


@pytest.fixture
def adapter():
    server = MagicMock()
    a = WhatsAppAdapter(
        "whatsapp", server, {"phone_number_id": "123", "access_token": "token"}
    )
    a.is_initialized = True
    a.session = MagicMock()
    return a


@pytest.mark.asyncio
async def test_whatsapp_webhook_content_extraction(adapter):
    cases = [
        ("video", {"id": "v1"}, "[Video]"),
        ("audio", {"id": "a1"}, "[Audio]"),
        ("document", {"id": "d1", "filename": "f.txt"}, "[Document: f.txt]"),
        ("contacts", [{"name": {"formatted_name": "John"}}], "[Contact]"),
    ]
    for mtype, mdata, expected in cases:
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
                                        "type": mtype,
                                        mtype: mdata,
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        msg = await adapter.handle_webhook(data)
        assert msg.content == expected


@pytest.mark.asyncio
async def test_whatsapp_send_via_openclaw_success(adapter):
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
    adapter._use_openclaw = True

    res = await adapter._send_via_openclaw("chat1", "text", "text")
    assert res.id == "oc123"
    assert res.metadata["source"] == "openclaw"


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_error_path(adapter):
    # Invalid data to trigger exception
    data = {"entry": [{"changes": [None]}]}
    res = await adapter.handle_webhook(data)
    assert res is None


@pytest.mark.asyncio
async def test_whatsapp_init_direct_api_success_2(adapter):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__.return_value = mock_resp
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        assert await adapter._init_direct_api()


@pytest.mark.asyncio
async def test_whatsapp_initialize_exception(adapter):
    """Test initialize with exception (lines 45-47)"""
    with patch.object(adapter, "_init_openclaw", side_effect=Exception("Crash")):
        assert await adapter.initialize() is False


@pytest.mark.asyncio
async def test_whatsapp_init_direct_api_no_phone(adapter):
    """Test _init_direct_api with no phone_number_id (lines 88-89)"""
    adapter.phone_number_id = None
    assert await adapter._init_direct_api() is False


@pytest.mark.asyncio
async def test_whatsapp_add_group_participant_exception(adapter):
    """Test add_group_participant with exception (lines 648-649)"""
    # Trigger exception by making group_chats something that fails __contains__
    adapter.group_chats = None
    assert await adapter.add_group_participant("g1", "p1") is False


@pytest.mark.asyncio
async def test_whatsapp_get_message_status_full(adapter):
    """Test get_message_status various paths (lines 655-662)"""
    # 1. Success path (lines 655-659)
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "delivered"})
    mock_resp.__aenter__.return_value = mock_resp
    adapter.session.get.return_value = mock_resp

    res = await adapter.get_message_status("m1")
    assert res == {"status": "delivered"}

    # 2. Exception path (lines 661-662)
    adapter.session.get.side_effect = Exception("API error")
    res = await adapter.get_message_status("m1")
    assert res == {"status": "unknown"}


@pytest.mark.asyncio
async def test_whatsapp_upload_media_no_session(adapter):
    """Test _upload_media with no session (line 842)"""
    adapter.session = None
    assert await adapter._upload_media("path", MessageType.IMAGE) is None


@pytest.mark.asyncio
async def test_whatsapp_init_direct_api_exception(adapter):
    """Test _init_direct_api with exception (lines 101-103)"""
    with patch("aiohttp.ClientSession", side_effect=Exception("Session Error")):
        assert await adapter._init_direct_api() is False


@pytest.mark.asyncio
async def test_whatsapp_create_group_full(adapter):
    """Test create_group various paths (lines 623-638)"""
    # 1. OpenClaw success (lines 623-630)
    adapter._openclaw = AsyncMock()
    adapter._openclaw.execute_tool.return_value = {"result": {"group_id": "g123"}}
    adapter._use_openclaw = True
    assert await adapter.create_group("name", ["p1"]) == "g123"

    # 2. Fallback path (lines 632-635)
    adapter._use_openclaw = False
    gid = await adapter.create_group("name2", ["p2"])
    assert gid.startswith("group_")
    assert adapter.group_chats[gid]["name"] == "name2"


@pytest.mark.asyncio
async def test_whatsapp_add_group_participant_success(adapter):
    """Test add_group_participant success path (lines 644-647)"""
    adapter.group_chats = {"g1": {"participants": ["p1"]}}
    assert await adapter.add_group_participant("g1", "p2") is True
    assert "p2" in adapter.group_chats["g1"]["participants"]


@pytest.mark.asyncio
async def test_whatsapp_get_message_status_no_session(adapter):
    """Test get_message_status returns 'sent' if no session (line 660)"""
    adapter.session = None
    res = await adapter.get_message_status("m1")
    assert res == {"status": "sent"}


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_statuses(adapter):
    """Test handle_webhook with statuses (lines 671-672)"""
    data = {
        "entry": [
            {"changes": [{"value": {"statuses": [{"id": "s1", "status": "read"}]}}]}
        ]
    }
    with patch.object(
        adapter, "_notify_callbacks", new_callable=AsyncMock
    ) as mock_notify:
        res = await adapter.handle_webhook(data)
        assert res is None
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_send_with_retry_no_session(adapter):
    """Test _send_with_retry with no session (line 738)"""
    adapter.session = None
    assert await adapter._send_with_retry({}) is None


def test_whatsapp_mime_helpers(adapter):
    """Test MIME helper methods (lines 939, 944, 958-964)"""
    # _mime_to_message_type (939, 944)
    assert adapter._mime_to_message_type("image/png") == MessageType.IMAGE
    assert adapter._mime_to_message_type("application/pdf") == MessageType.DOCUMENT

    # _get_mime_type (958-964)
    with patch("mimetypes.guess_type", return_value=(None, None)):
        assert adapter._get_mime_type("file.xyz", MessageType.IMAGE) == "image/jpeg"
        assert adapter._get_mime_type("file.xyz", MessageType.VIDEO) == "video/mp4"
        assert adapter._get_mime_type("file.xyz", MessageType.AUDIO) == "audio/mpeg"
        assert (
            adapter._get_mime_type("file.xyz", MessageType.DOCUMENT)
            == "application/pdf"
        )


@pytest.mark.asyncio
async def test_whatsapp_create_group_exception(adapter):
    """Test create_group exception (lines 636-638)"""
    # Trigger exception by making group_chats something that fails assignment
    with patch.object(adapter, "_use_openclaw", False):
        adapter.group_chats = None
        assert await adapter.create_group("name", []) is None


@pytest.mark.asyncio
async def test_whatsapp_add_group_participant_not_found(adapter):
    """Test add_group_participant with missing group (line 647)"""
    adapter.group_chats = {}
    assert await adapter.add_group_participant("unknown_g", "p1") is False
