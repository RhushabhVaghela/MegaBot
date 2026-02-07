"""Final coverage completion tests to achieve 100% coverage"""

import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock
from adapters.messaging.whatsapp import WhatsAppAdapter
from adapters.messaging.server import MessageType
from core.admin_handler import AdminHandler


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

        result = await wa_adapter._send_media_via_openclaw(
            "chat1", "path/to/img.jpg", "caption", MessageType.IMAGE
        )
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
        data_status = {
            "entry": [{"changes": [{"value": {"statuses": [{"id": "s1"}]}}]}]
        }
        result = await wa_adapter.handle_webhook(data_status)
        assert result is None

        # Test interactive message
        data_interactive = {
            "entry": [
                {
                    "changes": [
                        {"value": {"messages": [{"id": "m1", "type": "interactive"}]}}
                    ]
                }
            ]
        }
        result = await wa_adapter.handle_webhook(data_interactive)
        assert result is None

        # Test media types
        media_types = ["image", "video", "audio", "document", "location", "contacts"]
        for t in media_types:
            data = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {"id": "m1", "type": t, "from": "u1", t: {}}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
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
        assert (
            wa_adapter._mime_to_message_type("application/pdf") == MessageType.DOCUMENT
        )


class TestAdminHandlerCoverage:
    """Target missing lines in core/admin_handler.py"""

    @pytest.mark.asyncio
    async def test_execute_approved_action_mcp(self, orchestrator):
        handler = AdminHandler(orchestrator)
        orchestrator.adapters = {"mcp": AsyncMock()}
        orchestrator.adapters["mcp"].call_tool.return_value = "Success"

        action = {
            "type": "mcp_tool",
            "payload": {"server": "s1", "tool": "t1", "params": {}},
        }
        result = await handler._execute_approved_action(action)
        assert result == "Success"

    @pytest.mark.asyncio
    async def test_execute_approved_action_file(self, orchestrator, tmp_path):
        handler = AdminHandler(orchestrator)
        test_file = tmp_path / "test.txt"

        # Patch PROJECT_ROOT so tmp_path is considered within the allowed tree
        with patch.object(AdminHandler, "PROJECT_ROOT", tmp_path):
            # Write
            action_write = {
                "type": "file_operation",
                "payload": {
                    "operation": "write",
                    "path": str(test_file),
                    "content": "hello",
                },
            }
            await handler._execute_approved_action(action_write)
            assert test_file.read_text() == "hello"

            # Read
            action_read = {
                "type": "file_operation",
                "payload": {"operation": "read", "path": str(test_file)},
            }
            res = await handler._execute_approved_action(action_read)
            assert res == "hello"

    @pytest.mark.asyncio
    async def test_execute_approved_action_openclaw(self, orchestrator):
        handler = AdminHandler(orchestrator)
        orchestrator.adapters = {"openclaw": AsyncMock()}
        orchestrator.adapters["openclaw"].execute_tool.return_value = "Done"

        action = {"type": "generic", "payload": {"method": "m1", "params": {}}}
        result = await handler._execute_approved_action(action)
        assert result == "Done"

    @pytest.mark.asyncio
    async def test_execute_approved_action_error(self, orchestrator):
        handler = AdminHandler(orchestrator)
        # Force exception
        action = {"type": "mcp_tool", "payload": None}
        result = await handler._execute_approved_action(action)
        assert result is not None
        assert "execution failed" in str(result)


class TestLLMProviderCoverage:
    """Target missing lines in core/llm_providers.py"""

    @pytest.mark.asyncio
    async def test_openai_provider_error_paths(self):
        from core.llm_providers import OpenAIProvider

        p = OpenAIProvider(api_key="key")

        # API missing key
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        # Connection failed
        p.api_key = "key"
        with patch("aiohttp.ClientSession.post", side_effect=Exception("Conn fail")):
            assert "connection failed" in await p.generate("hi")

        # Error status
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Server error")
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        with patch("aiohttp.ClientSession.post", return_value=mock_cm):
            assert "error: 500" in await p.generate("hi")

    @pytest.mark.asyncio
    async def test_anthropic_provider_error_paths(self):
        from core.llm_providers import AnthropicProvider

        p = AnthropicProvider(api_key="key")
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        p.api_key = "key"
        with patch("aiohttp.ClientSession.post", side_effect=Exception("Fail")):
            assert "connection failed" in await p.generate("hi")

    @pytest.mark.asyncio
    async def test_gemini_provider_error_paths(self):
        from core.llm_providers import GeminiProvider

        p = GeminiProvider(api_key="key")
        p.api_key = None
        assert "key missing" in await p.generate("hi")

        p.api_key = "key"
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"candidates": []})  # No candidates
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        with patch("aiohttp.ClientSession.post", return_value=mock_cm):
            assert "No candidates" in await p.generate("hi")


class TestOrchestratorCoverage:
    """Target missing lines in core/orchestrator.py"""

    @pytest.mark.asyncio
    async def test_shutdown_error_handling(self, orchestrator):
        # Force an adapter to fail during shutdown
        bad_adapter = MagicMock()
        bad_adapter.shutdown = AsyncMock(side_effect=Exception("Boom"))
        orchestrator.adapters = {"bad": bad_adapter}

        # Should catch and log error, not crash
        await orchestrator.shutdown()
        assert bad_adapter.shutdown.called

    def test_sanitize_output_with_various_inputs(self, orchestrator):
        assert orchestrator._sanitize_output(None) == ""
        assert orchestrator._sanitize_output("Safe") == "Safe"
        assert "\x1b" not in orchestrator._sanitize_output("\x1b[31mRed\x1b[0m")

    @pytest.mark.asyncio
    async def test_check_identity_claims_none(self, orchestrator):
        orchestrator.llm = AsyncMock()
        orchestrator.llm.generate.return_value = "NONE"
        # Must contain trigger words to call LLM
        await orchestrator._check_identity_claims("I AM nobody", "p1", "id1", "c1")
        assert orchestrator.llm.generate.called


class TestConfigCoverage:
    """Target missing lines in core/config.py"""

    def test_validate_environment_missing(self):
        from core.config import Config, SystemConfig, SecurityConfig

        c = Config(
            system=SystemConfig(), adapters={}, paths={}, security=SecurityConfig()
        )
        # Force missing env
        with patch.dict("os.environ", {}, clear=True):
            assert c.validate_environment() is False

    def test_load_config_not_found(self, tmp_path):
        from core.config import load_config

        path = str(tmp_path / "notfound.yaml")
        # Should create default and return it
        cfg = load_config(path)
        assert cfg.system.name == "MegaBot"
        assert os.path.exists(path)
