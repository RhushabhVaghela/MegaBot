"""Consolidated WhatsApp adapter tests.

Merged from: test_whatsapp_coverage.py, test_whatsapp_coverage_2.py,
test_whatsapp_coverage_3.py, test_whatsapp_coverage_4.py,
test_whatsapp_coverage_final.py, test_whatsapp_final.py, test_whatsapp_boost.py
"""

import io
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_server():
    server = MagicMock()
    server.openclaw = None
    return server


@pytest.fixture
def adapter(mock_server):
    a = WhatsAppAdapter("whatsapp", mock_server, {"phone_number_id": "123", "access_token": "token"})
    a.is_initialized = True
    a.session = MagicMock()
    return a


# ── Helpers ───────────────────────────────────────────────────────────


def _make_webhook_data(msg_type, msg_data, msg_from="u", msg_id="m"):
    """Build a standard WhatsApp webhook payload."""
    msg = {"from": msg_from, "id": msg_id, "type": msg_type}
    if isinstance(msg_data, dict):
        msg.update(msg_data)
    else:
        msg[msg_type] = msg_data
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def _mock_response(status=200, json_data=None, read_data=None, text_data=None):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    if read_data is not None:
        resp.read = AsyncMock(return_value=read_data)
    if text_data is not None:
        resp.text = AsyncMock(return_value=text_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


# ── Initialization Tests ──────────────────────────────────────────────


class TestInitialization:
    @pytest.mark.asyncio
    async def test_initialize_openclaw_success_from_config(self, mock_server):
        """Init with openclaw config creates adapter and connects."""
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
    async def test_initialize_openclaw_from_server(self, mock_server):
        """Init picks up openclaw from server if available."""
        mock_server.openclaw = AsyncMock()
        adapter = WhatsAppAdapter("whatsapp", mock_server, {})
        success = await adapter.initialize()
        assert success
        assert adapter._openclaw == mock_server.openclaw

    @pytest.mark.asyncio
    async def test_initialize_direct_api_success(self, mock_server):
        """Init falls back to direct API when openclaw fails."""
        config = {"phone_number_id": "123", "access_token": "token"}
        adapter = WhatsAppAdapter("whatsapp", mock_server, config)
        with patch.object(adapter, "_init_openclaw", return_value=False):
            mock_resp = _mock_response(200)
            with patch("aiohttp.ClientSession.get", return_value=mock_resp):
                success = await adapter.initialize()
                assert success
                assert adapter.is_initialized

    @pytest.mark.asyncio
    async def test_initialize_all_paths(self, mock_server):
        """Comprehensive: openclaw from server, from config, and direct API."""
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
            mock_resp = _mock_response(200)
            with patch("aiohttp.ClientSession.get", return_value=mock_resp):
                a3 = WhatsAppAdapter("wa", mock_server, {"phone_number_id": "123"})
                assert await a3.initialize()

    @pytest.mark.asyncio
    async def test_init_openclaw_exception(self, mock_server):
        """_init_openclaw handles exceptions gracefully."""
        adapter = WhatsAppAdapter("whatsapp", mock_server, {})
        with patch("adapters.openclaw_adapter.OpenClawAdapter", side_effect=Exception("Err")):
            success = await adapter._init_openclaw()
            assert not success

    @pytest.mark.asyncio
    async def test_init_openclaw_manual(self, adapter):
        """_init_openclaw with explicit OpenClawAdapter creation."""
        adapter.server.openclaw = None
        with patch("adapters.openclaw_adapter.OpenClawAdapter") as mock_oc:
            mock_oc.return_value.connect = AsyncMock()
            success = await adapter._init_openclaw()
            assert success
            assert adapter._use_openclaw

    @pytest.mark.asyncio
    async def test_init_direct_api_fail(self, mock_server):
        """_init_direct_api returns False on non-200 response."""
        adapter = WhatsAppAdapter("whatsapp", mock_server, {"phone_number_id": "123"})
        mock_resp = _mock_response(401)
        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            success = await adapter._init_direct_api()
            assert not success

    @pytest.mark.asyncio
    async def test_init_direct_api_success_standalone(self, adapter):
        """_init_direct_api returns True on 200."""
        mock_resp = _mock_response(200)
        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            assert await adapter._init_direct_api()

    @pytest.mark.asyncio
    async def test_init_direct_api_no_phone(self, adapter):
        """_init_direct_api returns False when phone_number_id is None."""
        adapter.phone_number_id = None
        assert await adapter._init_direct_api() is False

    @pytest.mark.asyncio
    async def test_init_direct_api_exception(self, adapter):
        """_init_direct_api returns False on session creation error."""
        with patch("aiohttp.ClientSession", side_effect=Exception("Session Error")):
            assert await adapter._init_direct_api() is False

    @pytest.mark.asyncio
    async def test_initialize_exception(self, adapter):
        """initialize returns False when _init_openclaw raises."""
        with patch.object(adapter, "_init_openclaw", side_effect=Exception("Crash")):
            assert await adapter.initialize() is False


# ── Send Text Tests ───────────────────────────────────────────────────


class TestSendText:
    @pytest.mark.asyncio
    async def test_send_text_openclaw(self, adapter):
        """send_text via openclaw returns message with openclaw id."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
        msg = await adapter.send_text("chat1", "hello")
        assert msg.id == "oc123"

    @pytest.mark.asyncio
    async def test_send_text_direct(self, adapter):
        """send_text via direct API returns message with WA id."""
        adapter.session.post.return_value = _mock_response(200, json_data={"messages": [{"id": "wa123"}]})
        msg = await adapter.send_text("chat1", "hello")
        assert msg.id == "wa123"

    @pytest.mark.asyncio
    async def test_send_text_retry_and_error(self, adapter):
        """send_text returns None after exhausting retries."""
        adapter.session.post.return_value = _mock_response(500)
        with patch("asyncio.sleep", return_value=None):
            msg = await adapter.send_text("chat1", "hi")
            assert msg is None

    @pytest.mark.asyncio
    async def test_send_text_various(self, adapter):
        """send_text openclaw then direct in sequence."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc1"}}
        msg = await adapter.send_text("c1", "hi")
        assert msg.id == "oc1"

        adapter._use_openclaw = False
        adapter.session.post.return_value = _mock_response(200, json_data={"messages": [{"id": "wa1"}]})
        msg = await adapter.send_text("c1", "hi")
        assert msg.id == "wa1"


# ── Send Media Tests ──────────────────────────────────────────────────


class TestSendMedia:
    @pytest.mark.asyncio
    async def test_send_media_openclaw(self, adapter):
        """send_media via openclaw."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
        msg = await adapter.send_media("chat1", "path.png")
        assert msg.id == "oc123"

    @pytest.mark.asyncio
    async def test_send_media_direct(self, adapter):
        """send_media with mocked _upload_media and _send_with_retry."""
        adapter._use_openclaw = False
        adapter._upload_media = AsyncMock(return_value="med123")
        adapter._send_with_retry = AsyncMock(return_value={"messages": [{"id": "m1"}]})
        res = await adapter.send_media("c1", "p.png")
        assert res.id == "m1"

    @pytest.mark.asyncio
    async def test_send_media_various(self, adapter):
        """send_media openclaw then direct with real upload flow."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc2"}}
        msg = await adapter.send_media("c1", "p.png")
        assert msg.id == "oc2"

        adapter._use_openclaw = False
        mock_resp_up = _mock_response(200, json_data={"id": "med1"})
        mock_resp_msg = _mock_response(200, json_data={"messages": [{"id": "wa2"}]})
        adapter.session.post.side_effect = [mock_resp_up, mock_resp_msg]
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "builtins.open",
                side_effect=lambda *args, **kwargs: io.BytesIO(b"a"),
            ),
        ):
            msg = await adapter.send_media("c1", "p.png")
            assert msg.id == "wa2"


# ── Send Location / Contact Tests ────────────────────────────────────


class TestSendLocationContact:
    @pytest.mark.asyncio
    async def test_send_location_direct_with_address(self, adapter):
        """send_location direct API with address and name."""
        adapter.session.post.return_value = _mock_response(200, json_data={"messages": [{"id": "loc123"}]})
        msg = await adapter.send_location("chat1", 1.0, 2.0, address="Addr", name="Place")
        assert msg.id == "loc123"

    @pytest.mark.asyncio
    async def test_send_location_openclaw(self, adapter):
        """send_location via openclaw."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc_loc"}}
        msg = await adapter.send_location("chat1", 1.0, 2.0)
        assert msg.id == "oc_loc"

    @pytest.mark.asyncio
    async def test_send_location_openclaw_fail(self, adapter):
        """send_location openclaw error returns fallback id."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"error": "fail"}
        res = await adapter.send_location("c1", 0, 0)
        assert res.id.startswith("wa_")

    @pytest.mark.asyncio
    async def test_send_contact_direct(self, adapter):
        """send_contact direct API."""
        adapter.session.post.return_value = _mock_response(200, json_data={"messages": [{"id": "con123"}]})
        msg = await adapter.send_contact("chat1", {"name": "John", "phone": "123"})
        assert msg.id == "con123"

    @pytest.mark.asyncio
    async def test_send_contact_direct_fail(self, adapter):
        """send_contact direct API returns None on failure."""
        adapter._use_openclaw = False
        adapter.session.post.return_value.__aenter__.return_value.status = 400
        with patch("asyncio.sleep", return_value=None):
            res = await adapter.send_contact("c1", {"name": "N"})
            assert res is None

    @pytest.mark.asyncio
    async def test_location_and_contact_combined(self, adapter):
        """send_location and send_contact in sequence."""
        adapter.session.post.return_value = _mock_response(200, json_data={"messages": [{"id": "id1"}]})
        msg_loc = await adapter.send_location("c1", 0, 0)
        assert msg_loc.id == "id1"

        msg_con = await adapter.send_contact("c1", {"name": "N", "phone": "P"})
        assert msg_con.id == "id1"


# ── Webhook Tests ─────────────────────────────────────────────────────


class TestWebhook:
    @pytest.mark.asyncio
    async def test_handle_webhook_text(self, adapter):
        """Webhook with text message."""
        data = _make_webhook_data(
            "text",
            {"text": {"body": "hello"}},
            msg_from="user1",
            msg_id="m1",
        )
        msg = await adapter.handle_webhook(data)
        assert msg.content == "hello"

    @pytest.mark.asyncio
    async def test_handle_webhook_image(self, adapter):
        """Webhook with image message downloads media."""
        data = _make_webhook_data(
            "image",
            {"image": {"id": "media1", "mime_type": "image/png"}},
            msg_from="user1",
            msg_id="m2",
        )
        mock_resp_url = _mock_response(200, json_data={"url": "http://media-url"})
        mock_resp_data = _mock_response(200, read_data=b"bytes")
        adapter.session.get.side_effect = [mock_resp_url, mock_resp_data]

        with patch("aiofiles.open", return_value=AsyncMock()):
            msg = await adapter.handle_webhook(data)
            assert msg.message_type == MessageType.IMAGE

    @pytest.mark.asyncio
    async def test_handle_webhook_text_and_image(self, adapter):
        """Webhook text then image in sequence."""
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
        mock_resp = _mock_response(200, json_data={"url": "http://media-url"})
        mock_resp.read = AsyncMock(return_value=b"bytes")
        adapter.session.get.return_value = mock_resp
        msg = await adapter.handle_webhook(data)
        assert msg.message_type == MessageType.IMAGE

    @pytest.mark.asyncio
    async def test_handle_webhook_interactive_button_reply(self, adapter):
        """Webhook interactive button_reply extracts title."""
        data_btn = _make_webhook_data(
            "interactive",
            {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"title": "Yes", "id": "y1"},
                }
            },
            msg_from="u1",
            msg_id="m1",
        )
        msg = await adapter.handle_webhook(data_btn)
        assert msg.content == "Yes"

    @pytest.mark.asyncio
    async def test_handle_webhook_interactive_list_reply(self, adapter):
        """Webhook interactive list_reply extracts title."""
        data_list = _make_webhook_data(
            "interactive",
            {
                "interactive": {
                    "type": "list_reply",
                    "list_reply": {"title": "Opt1", "id": "o1"},
                }
            },
            msg_from="u1",
            msg_id="m1",
        )
        msg = await adapter.handle_webhook(data_list)
        assert msg.content == "Opt1"

    @pytest.mark.asyncio
    async def test_handle_webhook_location(self, adapter):
        """Webhook location message."""
        data_loc = _make_webhook_data(
            "location",
            {"location": {"latitude": 1, "longitude": 2}},
            msg_from="u1",
            msg_id="m1",
        )
        msg = await adapter.handle_webhook(data_loc)
        assert "Location" in msg.content

    @pytest.mark.asyncio
    async def test_handle_webhook_media_branches(self, adapter):
        """Webhook loops through all media types: image/video/audio/doc/location/contacts."""
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
    async def test_handle_webhook_content_extraction(self, adapter):
        """Webhook content extraction for video/audio/document/contacts."""
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
    async def test_handle_webhook_extra_media_types(self, adapter):
        """Webhook video/audio/document content strings."""
        adapter.session = AsyncMock()
        base = {"entry": [{"changes": [{"value": {"messages": [{"from": "u", "id": "m", "type": ""}]}}]}]}
        base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "video"
        msg = await adapter.handle_webhook(base)
        assert msg.content == "[Video]"

        base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "audio"
        msg = await adapter.handle_webhook(base)
        assert msg.content == "[Audio]"

        base["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "document"
        base["entry"][0]["changes"][0]["value"]["messages"][0]["document"] = {"filename": "f.txt"}
        msg = await adapter.handle_webhook(base)
        assert "f.txt" in msg.content

    @pytest.mark.asyncio
    async def test_handle_webhook_empty(self, adapter):
        """Webhook with empty data returns None."""
        assert await adapter.handle_webhook({}) is None

    @pytest.mark.asyncio
    async def test_handle_webhook_no_messages(self, adapter):
        """Webhook with no messages key returns None."""
        assert await adapter.handle_webhook({"entry": [{"changes": [{"value": {}}]}]}) is None

    @pytest.mark.asyncio
    async def test_handle_webhook_error_path(self, adapter):
        """Webhook with invalid data triggers exception path."""
        data = {"entry": [{"changes": [None]}]}
        res = await adapter.handle_webhook(data)
        assert res is None

    @pytest.mark.asyncio
    async def test_handle_webhook_statuses(self, adapter):
        """Webhook with statuses notifies callbacks and returns None."""
        data = {"entry": [{"changes": [{"value": {"statuses": [{"id": "s1", "status": "read"}]}}]}]}
        with patch.object(adapter, "_notify_callbacks", new_callable=AsyncMock) as mock_notify:
            res = await adapter.handle_webhook(data)
            assert res is None
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_webhook_full(self, adapter):
        """Comprehensive: text, interactive, location webhook in sequence."""
        # Text
        data = _make_webhook_data(
            "text",
            {"text": {"body": "hi"}},
            msg_from="u1",
            msg_id="m1",
        )
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
        data_loc = _make_webhook_data(
            "location",
            {"location": {"latitude": 1, "longitude": 2}},
            msg_from="u1",
            msg_id="m1",
        )
        msg = await adapter.handle_webhook(data_loc)
        assert "Location" in msg.content


# ── Upload Media Tests ────────────────────────────────────────────────


class TestUploadMedia:
    @pytest.mark.asyncio
    async def test_upload_media_error_nonexistent(self, adapter):
        """_upload_media returns None for nonexistent file."""
        adapter.session = AsyncMock()
        res = await adapter._upload_media("nonexistent.png", MessageType.IMAGE)
        assert res is None

    @pytest.mark.asyncio
    async def test_upload_media_error_400(self, adapter):
        """_upload_media returns None on 400 response."""
        adapter.session.post.return_value = _mock_response(400, text_data="Error")
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("aiohttp.FormData") as mock_form_data:
                    mock_form = MagicMock()
                    mock_form_data.return_value = mock_form
                    res = await adapter._upload_media("file.png", MessageType.IMAGE)
                    assert res is None

    @pytest.mark.asyncio
    async def test_upload_media_success(self, adapter):
        """_upload_media returns media id on success."""
        adapter.session.post.return_value = _mock_response(200, json_data={"id": "up_id"})
        with patch("os.path.exists", return_value=True):
            with patch(
                "builtins.open",
                side_effect=lambda *args, **kwargs: io.BytesIO(b"abc"),
            ):
                res = await adapter._upload_media("file.png", MessageType.IMAGE)
                assert res == "up_id"

    @pytest.mark.asyncio
    async def test_upload_media_success_and_fail_branches(self, adapter):
        """_upload_media success then failure through session mock."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "builtins.open",
                side_effect=lambda *args, **kwargs: io.BytesIO(b"a"),
            ),
        ):
            adapter.session.post.return_value.__aenter__.return_value.status = 200
            adapter.session.post.return_value.__aenter__.return_value.json = AsyncMock(return_value={"id": "up1"})
            assert await adapter._upload_media("p.png", MessageType.IMAGE) == "up1"

            adapter.session.post.return_value.__aenter__.return_value.status = 401
            assert await adapter._upload_media("p.png", MessageType.IMAGE) is None

    @pytest.mark.asyncio
    async def test_upload_media_no_session(self, adapter):
        """_upload_media returns None when session is None."""
        adapter.session = None
        assert await adapter._upload_media("path", MessageType.IMAGE) is None

    @pytest.mark.asyncio
    async def test_upload_media_fail_status(self, adapter):
        """_upload_media returns None on 400 with AsyncMock session."""
        adapter.session = AsyncMock()
        with patch("os.path.exists", return_value=True):
            with patch(
                "builtins.open",
                side_effect=lambda *args, **kwargs: io.BytesIO(b"abc"),
            ):
                adapter.session.post.return_value.__aenter__.return_value.status = 400
                adapter.session.post.return_value.__aenter__.return_value.text = AsyncMock(return_value="fail")
                res = await adapter._upload_media("p.png", MessageType.IMAGE)
                assert res is None


# ── OpenClaw Path Tests ───────────────────────────────────────────────


class TestOpenClawPaths:
    @pytest.mark.asyncio
    async def test_send_via_openclaw_success(self, adapter):
        """_send_via_openclaw returns message with openclaw source."""
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc123"}}
        adapter._use_openclaw = True
        res = await adapter._send_via_openclaw("chat1", "text", "text")
        assert res.id == "oc123"
        assert res.metadata["source"] == "openclaw"

    @pytest.mark.asyncio
    async def test_send_via_openclaw_error(self, adapter):
        """_send_via_openclaw returns None on exception."""
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.side_effect = Exception("OC Fail")
        res = await adapter._send_via_openclaw("c1", "txt", "text")
        assert res is None

    @pytest.mark.asyncio
    async def test_send_media_via_openclaw_success(self, adapter):
        """_send_media_via_openclaw returns message on success."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"message_id": "oc_med"}}
        res = await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE)
        assert res.id == "oc_med"

    @pytest.mark.asyncio
    async def test_send_media_via_openclaw_error_result(self, adapter):
        """_send_media_via_openclaw returns None on error result."""
        adapter._use_openclaw = True
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"error": "fail"}
        assert await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE) is None

    @pytest.mark.asyncio
    async def test_send_media_via_openclaw_exception(self, adapter):
        """_send_media_via_openclaw returns None on exception."""
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.side_effect = Exception("OC Fail")
        res = await adapter._send_media_via_openclaw("c1", "p", "cap", MessageType.IMAGE)
        assert res is None


# ── Group Management Tests ────────────────────────────────────────────


class TestGroupManagement:
    @pytest.mark.asyncio
    async def test_create_group_openclaw(self, adapter):
        """create_group via openclaw."""
        adapter._openclaw = AsyncMock()
        adapter._openclaw.execute_tool.return_value = {"result": {"group_id": "g123"}}
        adapter._use_openclaw = True
        assert await adapter.create_group("name", ["p1"]) == "g123"

    @pytest.mark.asyncio
    async def test_create_group_fallback(self, adapter):
        """create_group fallback creates local group."""
        adapter._use_openclaw = False
        gid = await adapter.create_group("name2", ["p2"])
        assert gid.startswith("group_")
        assert adapter.group_chats[gid]["name"] == "name2"

    @pytest.mark.asyncio
    async def test_create_group_exception(self, adapter):
        """create_group returns None on exception."""
        with patch.object(adapter, "_use_openclaw", False):
            adapter.group_chats = None
            assert await adapter.create_group("name", []) is None

    @pytest.mark.asyncio
    async def test_add_group_participant_success(self, adapter):
        """add_group_participant adds participant to existing group."""
        adapter.group_chats = {"g1": {"participants": ["p1"]}}
        assert await adapter.add_group_participant("g1", "p2") is True
        assert "p2" in adapter.group_chats["g1"]["participants"]

    @pytest.mark.asyncio
    async def test_add_group_participant_not_found(self, adapter):
        """add_group_participant returns False for missing group."""
        adapter.group_chats = {}
        assert await adapter.add_group_participant("unknown_g", "p1") is False

    @pytest.mark.asyncio
    async def test_add_group_participant_exception(self, adapter):
        """add_group_participant returns False on exception."""
        adapter.group_chats = None
        assert await adapter.add_group_participant("g1", "p1") is False


# ── Message Status Tests ──────────────────────────────────────────────


class TestMessageStatus:
    @pytest.mark.asyncio
    async def test_get_message_status_success(self, adapter):
        """get_message_status returns status on success."""
        adapter.session.get.return_value = _mock_response(200, json_data={"status": "delivered"})
        res = await adapter.get_message_status("m1")
        assert res == {"status": "delivered"}

    @pytest.mark.asyncio
    async def test_get_message_status_exception(self, adapter):
        """get_message_status returns unknown on exception."""
        adapter.session.get.side_effect = Exception("API error")
        res = await adapter.get_message_status("m1")
        assert res == {"status": "unknown"}

    @pytest.mark.asyncio
    async def test_get_message_status_no_session(self, adapter):
        """get_message_status returns 'sent' when session is None."""
        adapter.session = None
        res = await adapter.get_message_status("m1")
        assert res == {"status": "sent"}


# ── Retry Logic Tests ────────────────────────────────────────────────


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_send_with_retry_success_after_fail(self, adapter):
        """_send_with_retry retries on 500 then succeeds."""
        mock_resp_fail = _mock_response(500)
        mock_resp_ok = _mock_response(200, json_data={"ok": True})
        adapter.session.post.side_effect = [mock_resp_fail, mock_resp_ok]
        with patch("asyncio.sleep", return_value=None):
            res = await adapter._send_with_retry({"p": 1})
            assert res == {"ok": True}
            assert adapter.session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_with_retry_rate_limit(self, adapter):
        """_send_with_retry retries on 429 then succeeds."""
        mock_resp_429 = _mock_response(429)
        mock_resp_ok = _mock_response(200, json_data={"ok": True})
        adapter.session.post.side_effect = [mock_resp_429, mock_resp_ok]
        with patch("asyncio.sleep", return_value=None):
            res = await adapter._send_with_retry({"p": 1})
            assert res == {"ok": True}

    @pytest.mark.asyncio
    async def test_send_with_retry_exception(self, adapter):
        """_send_with_retry returns None on exception."""
        adapter.session.post.side_effect = Exception("Transient")
        with patch("asyncio.sleep", return_value=None):
            res = await adapter._send_with_retry({"p": 1})
            assert res is None

    @pytest.mark.asyncio
    async def test_send_with_retry_no_session(self, adapter):
        """_send_with_retry returns None when session is None."""
        adapter.session = None
        assert await adapter._send_with_retry({}) is None


# ── Utility / Misc Tests ─────────────────────────────────────────────


class TestUtilities:
    @pytest.mark.asyncio
    async def test_notify_callbacks(self, adapter):
        """_notify_callbacks invokes all callbacks, even if one raises."""
        cb1 = AsyncMock()
        cb2 = MagicMock(side_effect=Exception("Fail"))
        adapter.register_notification_callback(cb1)
        adapter.register_notification_callback(cb2)
        await adapter._notify_callbacks({"data": 1})
        assert cb1.called
        assert cb2.called

    @pytest.mark.asyncio
    async def test_shutdown_and_utils(self, adapter):
        """Shutdown closes session; utility methods return expected values."""
        adapter._openclaw = MagicMock()
        await adapter.shutdown()
        assert adapter._normalize_phone("(123) 456-7890") == "+1234567890"
        assert adapter._map_media_type(MessageType.VIDEO) == "video"
        assert adapter._mime_to_message_type("audio/mp3") == MessageType.AUDIO
        assert adapter._get_mime_type("test.pdf", MessageType.DOCUMENT) == "application/pdf"

    @pytest.mark.asyncio
    async def test_shutdown_simple(self, adapter):
        """Shutdown calls session.close."""
        adapter.session.close = AsyncMock()
        await adapter.shutdown()
        assert adapter.session.close.called

    def test_format_text(self, adapter):
        """_format_text escapes markup when requested."""
        assert adapter._format_text("hi *bold*", markup=True) == "hi \\*bold\\*"
        assert adapter._format_text("hi", markup=False) == "hi"

    def test_mime_helpers(self, adapter):
        """MIME helper methods return correct types."""
        assert adapter._mime_to_message_type("image/png") == MessageType.IMAGE
        assert adapter._mime_to_message_type("application/pdf") == MessageType.DOCUMENT

        with patch("mimetypes.guess_type", return_value=(None, None)):
            assert adapter._get_mime_type("file.xyz", MessageType.IMAGE) == "image/jpeg"
            assert adapter._get_mime_type("file.xyz", MessageType.VIDEO) == "video/mp4"
            assert adapter._get_mime_type("file.xyz", MessageType.AUDIO) == "audio/mpeg"
            assert adapter._get_mime_type("file.xyz", MessageType.DOCUMENT) == "application/pdf"

    def test_detect_mime_type(self, adapter):
        """_detect_mime_type returns known type or fallback."""
        assert adapter._detect_mime_type("p.png") == "image/png"
        with patch("mimetypes.guess_type", return_value=(None, None)):
            assert adapter._detect_mime_type("p.unknown") == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_make_call(self, adapter):
        """make_call returns False (not supported)."""
        assert await adapter.make_call("c1") is False

    def test_get_contact_name(self, adapter):
        """_get_contact_name returns WhatsApp-prefixed phone."""
        assert adapter._get_contact_name("123") == "WhatsApp:123"

    @pytest.mark.asyncio
    async def test_utils_and_branches(self, adapter):
        """Utility methods: detect_mime_type, mime_to_message_type, map_media_type."""
        assert adapter._detect_mime_type("p.png") == "image/png"
        assert adapter._mime_to_message_type("video/mp4") == MessageType.VIDEO
        assert adapter._map_media_type(MessageType.STICKER) == "sticker"
        assert adapter._map_media_type(MessageType.TEXT) == "document"  # fallback

        await adapter.shutdown()
        assert adapter.session.close.called


# =====================================================================
# FROM test_coverage_completion_final.py
# =====================================================================


class TestWhatsAppCoverage:
    """Target missing lines in adapters/messaging/whatsapp.py"""

    @pytest.fixture
    def wa_adapter(self):
        server = MagicMock()
        return WhatsAppAdapter("whatsapp", server, {"access_token": "test-token"})

    @pytest.mark.asyncio
    async def test_whatsapp_init_openclaw_success(self):
        server = MagicMock()
        adapter = WhatsAppAdapter("whatsapp", server, {"access_token": "tok"})

        # Mock successful OpenClaw connection
        with patch("adapters.openclaw_adapter.OpenClawAdapter") as mock_oc_class:
            mock_oc = AsyncMock()
            mock_oc_class.return_value = mock_oc

            result = await adapter._init_openclaw()
            assert result is True
            assert adapter._use_openclaw is True

    @pytest.mark.asyncio
    async def test_whatsapp_send_media_via_openclaw_success(self, wa_adapter):
        mock_oc = AsyncMock()
        mock_oc.execute_tool.return_value = {"result": {"message_id": "oc_123"}}
        wa_adapter._openclaw = mock_oc
        wa_adapter._use_openclaw = True

        result = await wa_adapter._send_media_via_openclaw("chat1", "path/to/img.jpg", "caption", MessageType.IMAGE)
        assert result is not None
        assert result.id == "oc_123"

    @pytest.mark.asyncio
    async def test_whatsapp_upload_media_error_paths(self, wa_adapter):
        wa_adapter.session = AsyncMock()

        # File not exists
        result = await wa_adapter._upload_media("nonexistent.jpg", MessageType.IMAGE)
        assert result is None

        # API failure
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                mock_resp = MagicMock()
                mock_resp.status = 400
                mock_resp.text = AsyncMock(return_value="Error")
                wa_adapter.session.post.return_value.__aenter__.return_value = mock_resp

                result = await wa_adapter._upload_media("exists.jpg", MessageType.IMAGE)
                assert result is None

    @pytest.mark.asyncio
    async def test_whatsapp_webhook_various_types(self, wa_adapter):
        # Test status update
        data_status = {"entry": [{"changes": [{"value": {"statuses": [{"id": "s1"}]}}]}]}
        result = await wa_adapter.handle_webhook(data_status)
        assert result is None

        # Test interactive message
        data_interactive = {"entry": [{"changes": [{"value": {"messages": [{"id": "m1", "type": "interactive"}]}}]}]}
        result = await wa_adapter.handle_webhook(data_interactive)
        assert result is None

        # Test media types
        media_types = ["image", "video", "audio", "document", "location", "contacts"]
        for t in media_types:
            data = {"entry": [{"changes": [{"value": {"messages": [{"id": "m1", "type": t, "from": "u1", t: {}}]}}]}]}
            result = await wa_adapter.handle_webhook(data)
            assert result is not None
            assert result.sender_id == "u1"

    @pytest.mark.asyncio
    async def test_whatsapp_create_group_success(self, wa_adapter):
        # OpenClaw path
        mock_oc = AsyncMock()
        mock_oc.execute_tool.return_value = {"result": {"group_id": "g123"}}
        wa_adapter._openclaw = mock_oc
        wa_adapter._use_openclaw = True

        gid = await wa_adapter.create_group("New Group", ["p1"])
        assert gid == "g123"

        # Fallback path
        wa_adapter._use_openclaw = False
        gid2 = await wa_adapter.create_group("Local Group", ["p2"])
        assert gid2.startswith("group_")

    @pytest.mark.asyncio
    async def test_whatsapp_misc_methods(self, wa_adapter):
        # send_location OpenClaw path
        mock_oc = AsyncMock()
        mock_oc.execute_tool.return_value = {"result": {"message_id": "loc123"}}
        wa_adapter._openclaw = mock_oc
        wa_adapter._use_openclaw = True

        result = await wa_adapter.send_location("c1", 1.0, 2.0, name="Place")
        assert result.id == "loc123"

        # add_group_participant
        wa_adapter.group_chats["g1"] = {"participants": ["p1"]}
        assert await wa_adapter.add_group_participant("g1", "p2") is True
        assert "p2" in wa_adapter.group_chats["g1"]["participants"]
        assert await wa_adapter.add_group_participant("unknown", "p3") is False

    def test_whatsapp_helpers(self, wa_adapter):
        assert wa_adapter._normalize_phone("(123) 456-7890") == "+1234567890"
        assert wa_adapter._format_text("*Bold*", markup=True) == "\\*Bold\\*"
        assert wa_adapter._mime_to_message_type("image/png") == MessageType.IMAGE
        assert wa_adapter._mime_to_message_type("video/mp4") == MessageType.VIDEO
        assert wa_adapter._mime_to_message_type("audio/mpeg") == MessageType.AUDIO
        assert wa_adapter._mime_to_message_type("application/pdf") == MessageType.DOCUMENT
