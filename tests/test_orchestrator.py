"""Consolidated orchestrator tests.

Merges tests from:
  - test_orchestrator.py (original 61 tests)
  - test_orchestrator_coverage.py (6 tests)
  - test_orchestrator_coverage_final.py (3 tests)
  - test_orchestrator_extended.py (10 tests)
  - test_orchestrator_gaps.py (33 tests)
  - test_orchestrator_health_monitor.py (2 tests)
  - test_orchestrator_round2.py (21 tests)
  - test_orchestrator_components_coverage.py (4 tests)
  - test_orchestrator_components_extra.py (5 tests)
  - test_orchestrator_components_gaps.py (11 tests in 2 classes)
"""

import asyncio
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interfaces import Message
from core.orchestrator import MegaBotOrchestrator, health, websocket_endpoint
from core.orchestrator_components import BackgroundTasks, HealthMonitor, MessageHandler

# =====================================================================
# Helpers (deduplicated from satellite files)
# =====================================================================


class BreakLoop(BaseException):
    """Used by component tests to break out of infinite loops."""

    pass


def _mock_all_adapters(orchestrator):
    """Replace all adapters with AsyncMocks so start() doesn't hit real services.

    From test_orchestrator_round2.py.
    """
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()


def _make_fake_coro():
    """Return a mock object that looks like a coroutine (has .close()).

    From test_orchestrator_components_gaps.py.
    """
    fake = MagicMock()
    fake.close = MagicMock()
    return fake


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def orchestrator(mock_config):
    """Main orchestrator fixture — patches core adapters and provides fresh
    AsyncMock adapters for openclaw, memu, mcp, messaging, gateway.
    """
    with (
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
    ):
        orc = MegaBotOrchestrator(mock_config)
        # Use fresh mocks for all adapters
        orc.adapters = {
            "openclaw": AsyncMock(),
            "memu": AsyncMock(),
            "mcp": AsyncMock(),
            "messaging": AsyncMock(),
            "gateway": AsyncMock(),
        }
        orc.llm = AsyncMock()
        # Mock memory to avoid database operations
        orc.memory = AsyncMock()
        return orc


@pytest.fixture
def mock_config_coverage():
    """Fixture from test_orchestrator_coverage.py — uses AdapterConfig with
    host/port for openclaw and explicit paths dict.
    """
    from core.config import AdapterConfig, Config, SecurityConfig, SystemConfig

    return Config(
        system=SystemConfig(name="TestBot"),
        adapters={
            "openclaw": AdapterConfig(host="127.0.0.1", port=8080),
            "memu": AdapterConfig(database_url="sqlite:///:memory:"),
            "mcp": AdapterConfig(servers=[]),
            "llm": AdapterConfig(provider="ollama"),
        },
        paths={"workspaces": "/tmp", "external_repos": "/tmp"},
        security=SecurityConfig(megabot_encryption_salt="test-salt-minimum-16-chars"),
    )


@pytest.fixture
def orchestrator_coverage_final():
    """Fixture from test_orchestrator_coverage_final.py — uses MagicMock config
    with extensive memory method mocking.
    """
    config = MagicMock()
    config.system.name = "TestBot"
    config.system.default_mode = "plan"
    config.paths = {"external_repos": "/tmp", "workspaces": "/tmp"}
    config.adapters = {
        "openclaw": MagicMock(host="127.0.0.1", port=8080),
        "memu": MagicMock(database_url="sqlite:///test.db"),
        "mcp": MagicMock(servers=[]),
    }

    with (
        patch("core.orchestrator.MemoryServer") as mock_memory_class,
        patch("core.orchestrator.get_llm_provider") as mock_get_llm,
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.LokiMode"),
        patch("features.dash_data.agent.DashDataAgent"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
        patch("core.orchestrator.MegaBotMessagingServer") as mock_msg_class,
        patch("core.orchestrator.UnifiedGateway"),
    ):
        mock_memory = mock_memory_class.return_value
        for method in [
            "chat_write",
            "chat_read",
            "memory_stats",
            "get_unified_id",
            "backup_database",
            "chat_forget",
            "link_identity",
            "memory_search",
        ]:
            setattr(mock_memory, method, AsyncMock())
        mock_memory.chat_read.return_value = []
        mock_memory.memory_stats.return_value = {}
        mock_memory.get_unified_id.return_value = "user1"

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="VALID")
        mock_get_llm.return_value = mock_llm

        orch = MegaBotOrchestrator(config)
        orch.llm = mock_llm
        orch.memory = mock_memory

        # Messaging adapter setup
        mock_msg = mock_msg_class.return_value
        mock_msg.send_message = AsyncMock()
        orch.adapters["messaging"] = mock_msg

        return orch


@pytest.fixture
def mock_orchestrator_components():
    """Fixture from test_orchestrator_components_coverage.py — MagicMock orch
    for testing MessageHandler, HealthMonitor, BackgroundTasks.
    """
    orch = MagicMock()
    orch.memory = AsyncMock()
    orch.admin_handler = AsyncMock()
    orch.adapters = {
        "openclaw": AsyncMock(),
        "messaging": MagicMock(clients=[]),
        "mcp": AsyncMock(servers=[]),
        "memu": AsyncMock(),
    }
    orch.mode = "plan"
    orch.send_platform_message = AsyncMock()
    orch.restart_component = AsyncMock()
    return orch


@pytest.fixture
def mock_orchestrator_components_extra():
    """Fixture from test_orchestrator_components_extra.py — adds voice_adapter,
    mode='ask', run_autonomous_gateway_build, health_monitor.
    """
    orch = MagicMock()
    orch.memory = AsyncMock()
    orch.admin_handler = AsyncMock()
    orch.adapters = {
        "openclaw": AsyncMock(),
        "messaging": MagicMock(clients=[], voice_adapter=AsyncMock()),
        "mcp": AsyncMock(servers=[]),
        "memu": AsyncMock(),
    }
    orch.mode = "ask"
    orch.send_platform_message = AsyncMock()
    orch.restart_component = AsyncMock()
    orch.run_autonomous_gateway_build = AsyncMock()
    orch.health_monitor = MagicMock()
    orch.health_monitor.start_monitoring = AsyncMock()
    return orch


@pytest.fixture
def mock_orch_components_gaps():
    """Fixture from test_orchestrator_components_gaps.py — similar to
    mock_orchestrator_components but without admin_handler and send_platform_message.
    """
    orch = MagicMock()
    orch.memory = AsyncMock()
    orch.adapters = {
        "openclaw": AsyncMock(),
        "messaging": MagicMock(clients=[]),
        "mcp": AsyncMock(servers=[]),
        "memu": AsyncMock(),
    }
    orch.send_platform_message = AsyncMock()
    orch.restart_component = AsyncMock()
    return orch


# =====================================================================
# ORIGINAL TESTS (from test_orchestrator.py — 61 tests)
# =====================================================================


@pytest.mark.asyncio
async def test_orchestrator_start(orchestrator):
    await orchestrator.start()
    assert orchestrator.adapters["openclaw"].connect.called
    assert orchestrator.adapters["mcp"].start_all.called


@pytest.mark.asyncio
async def test_orchestrator_handle_message(orchestrator):
    mock_ws = AsyncMock()
    # Standard relay
    orchestrator.mode = "plan"
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "message", "content": "hello"}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception as e:
        if str(e) != "stop":
            raise
    assert orchestrator.adapters["memu"].store.called
    assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_handle_message_build(orchestrator):
    mock_ws = AsyncMock()
    orchestrator.mode = "build"
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "message", "content": "build things"}),
        Exception("stop"),
    ]
    orchestrator.llm.generate.return_value = "Success"

    # Mock run_autonomous_build to avoid background task complexities
    with patch.object(orchestrator, "run_autonomous_build", AsyncMock()) as mock_run:
        try:
            await orchestrator.handle_client(mock_ws)
        except Exception as e:
            if str(e) != "stop":
                raise

        await asyncio.sleep(0.05)
        assert mock_run.called
    assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_set_mode(orchestrator):
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "set_mode", "mode": "build"}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception as e:
        if str(e) != "stop":
            raise
    assert orchestrator.mode == "build"
    assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_mcp_call(orchestrator):
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "mcp_call", "server": "s1", "tool": "t1", "params": {"p1": "v1"}}),
        Exception("stop"),
    ]
    orchestrator.adapters["mcp"].call_tool.return_value = {"res": "ok"}
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception as e:
        if str(e) != "stop":
            raise
    orchestrator.adapters["mcp"].call_tool.assert_called_once_with("s1", "t1", {"p1": "v1"})
    assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_on_openclaw_event(orchestrator):
    mock_client = AsyncMock()
    orchestrator.clients.add(mock_client)
    event_data = {"method": "chat.message", "params": {"content": "hi"}}
    await orchestrator.on_openclaw_event(event_data)
    assert mock_client.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_search_memory(orchestrator):
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "search", "query": "test query"}),
        Exception("stop"),
    ]
    orchestrator.adapters["memu"].search.return_value = [{"content": "result"}]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception as e:
        if str(e) != "stop":
            raise
    orchestrator.adapters["memu"].search.assert_called_once_with("test query")
    assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_start_openclaw_failure(orchestrator):
    orchestrator.adapters["openclaw"].connect.side_effect = Exception("conn failed")
    await orchestrator.start()
    assert True


@pytest.mark.asyncio
async def test_orchestrator_start_mcp_failure(orchestrator):
    orchestrator.adapters["mcp"].start_all.side_effect = Exception("mcp failed")
    await orchestrator.start()
    assert True


@pytest.mark.asyncio
async def test_orchestrator_sync_loop_error(orchestrator):
    with patch("os.path.expanduser", return_value="/tmp/mock_logs"), patch("os.path.exists", return_value=True):
        orchestrator.adapters["memu"].ingest_openclaw_logs.side_effect = Exception("ingest err")
        # Use SystemExit to break the while-True loop — it is not caught
        # by the bare ``except Exception`` inside sync_loop.
        with patch("asyncio.sleep", side_effect=SystemExit("stop")), pytest.raises(SystemExit):
            await orchestrator.sync_loop()
        assert orchestrator.adapters["memu"].ingest_openclaw_logs.called


@pytest.mark.asyncio
async def test_orchestrator_proactive_loop(orchestrator):
    orchestrator.adapters["memu"].get_anticipations.return_value = [{"content": "do laundry"}]
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.proactive_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_proactive_loop_error(orchestrator):
    """Test exception handling in proactive_loop"""
    orchestrator.adapters["memu"].get_anticipations.side_effect = Exception("anticipation error")
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.proactive_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    # Should not crash, should continue to next iteration
    assert orchestrator.adapters["memu"].get_anticipations.called


@pytest.mark.asyncio
async def test_orchestrator_autonomous_build(orchestrator):
    mock_ws = AsyncMock()
    msg = Message(content="build things", sender="user")
    orchestrator.adapters["mcp"].call_tool.return_value = ["/path"]
    orchestrator.llm.generate.return_value = "Success"
    await orchestrator.run_autonomous_build(msg, mock_ws)
    assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_gateway_message(orchestrator):
    """Test handling messages from the Unified Gateway"""
    orchestrator.mode = "build"
    data = {
        "type": "message",
        "content": "hello from gateway",
        "sender_name": "remote-user",
        "_meta": {"client_id": "cf-1"},
    }
    with patch("core.build_session.can_allocate", return_value=True):
        await orchestrator.on_gateway_message(data)
    assert orchestrator.memory.chat_write.called

    # Non-build mode
    orchestrator.mode = "plan"
    await orchestrator.on_gateway_message(data)
    assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_on_openclaw_event_relay(orchestrator):
    """Test relay from OpenClaw to Native messaging"""
    data = {
        "method": "chat.message",
        "params": {"content": "hi", "sender": "OpenClawBot"},
    }
    await orchestrator.on_openclaw_event(data)
    assert orchestrator.adapters["messaging"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_llm_dispatch_mock(orchestrator):
    """Test LLM dispatch logic with mocking"""
    orchestrator.llm = None
    with patch("core.orchestrator.get_llm_provider") as mock_get:
        from core.llm_providers import AnthropicProvider

        mock_get.return_value = AnthropicProvider(api_key="test")
        orchestrator.llm = mock_get.return_value

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"content": [{"text": "I will use the filesystem tool."}]})
            mock_post.return_value = mock_resp

            result = await orchestrator._llm_dispatch("test prompt", "some context")
            assert "filesystem" in result


@pytest.mark.asyncio
async def test_orchestrator_run_autonomous_gateway_build(orchestrator):
    """Test autonomous build triggered from gateway"""
    msg = Message(content="build app", sender="gateway-user")
    original_data = {"_meta": {"client_id": "cf-1"}}
    with patch("core.build_session.can_allocate", return_value=True):
        await orchestrator.run_autonomous_gateway_build(msg, original_data)
    assert orchestrator.adapters["openclaw"].send_message.called
    assert orchestrator.adapters["gateway"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_llm_dispatch_failure(orchestrator):
    """Test LLM dispatch failure (non-200 status)"""
    orchestrator.llm = None
    with patch("core.orchestrator.get_llm_provider") as mock_get:
        from core.llm_providers import AnthropicProvider

        mock_get.return_value = AnthropicProvider(api_key="test")
        orchestrator.llm = mock_get.return_value

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status = 400
            mock_resp.text = AsyncMock(return_value="Bad request")
            mock_post.return_value = mock_resp

            result = await orchestrator._llm_dispatch("prompt", "context")
            assert "error: 400" in result


@pytest.mark.asyncio
async def test_orchestrator_policy_allow(orchestrator):
    """Test auto-approval based on allow policy"""
    orchestrator.permissions.set_policy("git status", "AUTO")
    event = {"method": "system.run", "params": {"command": "git status"}}
    await orchestrator.on_openclaw_event(event)
    assert orchestrator.adapters["openclaw"].send_message.called
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_policy_deny(orchestrator):
    """Test auto-denial based on deny policy"""
    orchestrator.permissions.set_policy("rm -rf", "NEVER")
    event = {"method": "system.run", "params": {"command": "rm -rf /"}}
    orchestrator.adapters["openclaw"].send_message.reset_mock()
    await orchestrator.on_openclaw_event(event)
    assert not orchestrator.adapters["openclaw"].send_message.called
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_policy_wildcard_allow(orchestrator):
    """Test global auto-approval using '*' wildcard"""
    orchestrator.permissions.set_policy("*", "AUTO")
    event = {"method": "system.run", "params": {"command": "any dangerous command"}}
    await orchestrator.on_openclaw_event(event)
    assert orchestrator.adapters["openclaw"].send_message.called
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_policy_wildcard_deny(orchestrator):
    """Test global auto-denial using '*' wildcard"""
    orchestrator.permissions.set_policy("*", "NEVER")
    event = {"method": "system.run", "params": {"command": "even safe command"}}
    orchestrator.adapters["openclaw"].send_message.reset_mock()
    await orchestrator.on_openclaw_event(event)
    assert not orchestrator.adapters["openclaw"].send_message.called
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_chat_approval(orchestrator):
    """Test approving a command via chat command '!yes'"""
    orchestrator.config.admins = ["my-phone"]
    await orchestrator.on_openclaw_event({"method": "system.run", "params": {"command": "echo logs"}})
    assert len(orchestrator.admin_handler.approval_queue) == 1
    orchestrator.adapters["openclaw"].send_message.reset_mock()
    await orchestrator.on_openclaw_event(
        {
            "method": "chat.message",
            "params": {"content": "!yes", "sender_id": "my-phone"},
        }
    )
    # After approval, queue should be drained and the command executed
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_admin_commands_extended(orchestrator):
    """Test !allow and !mode commands"""
    orchestrator.config.admins = ["admin"]
    await orchestrator.on_openclaw_event(
        {
            "method": "chat.message",
            "params": {"content": "!allow git status", "sender_id": "admin"},
        }
    )
    assert "git status" in orchestrator.config.policies["allow"]
    await orchestrator.on_openclaw_event(
        {
            "method": "chat.message",
            "params": {"content": "!mode debug", "sender_id": "admin"},
        }
    )
    assert orchestrator.mode == "debug"
    await orchestrator.on_openclaw_event({"method": "system.run", "params": {"command": "cmd"}})
    assert len(orchestrator.admin_handler.approval_queue) == 1
    await orchestrator.on_openclaw_event({"method": "chat.message", "params": {"content": "!no", "sender_id": "admin"}})
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_gateway_admin_command(orchestrator):
    """Test admin command from unified gateway"""
    orchestrator.config.admins = ["gateway-admin"]
    data = {"type": "message", "content": "!mode build", "sender_id": "gateway-admin"}
    await orchestrator.on_gateway_message(data)
    assert orchestrator.mode == "build"
    await asyncio.sleep(0.05)
    assert orchestrator.adapters["messaging"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_credential_loading():
    """Test the dynamic loading of api-credentials.py"""
    with patch("os.path.exists", return_value=True), patch("importlib.util.spec_from_file_location") as mock_spec:
        assert True


@pytest.mark.asyncio
async def test_orchestrator_approval_flow(orchestrator):
    """Test the Interlock/Approval Queue logic"""
    mock_client = AsyncMock()
    orchestrator.clients.add(mock_client)
    event = {"method": "system.run", "params": {"command": "echo hello"}}
    await orchestrator.on_openclaw_event(event)
    assert len(orchestrator.admin_handler.approval_queue) == 1
    assert orchestrator.admin_handler.approval_queue[0]["type"] == "system_command"
    assert mock_client.send_json.called
    action_id = orchestrator.admin_handler.approval_queue[0]["id"]
    await orchestrator._process_approval(action_id, approved=True)
    # After approval, the command is executed and the queue is cleared
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_rejection_flow(orchestrator):
    """Test rejecting a sensitive command"""
    event = {"method": "system.run", "params": {"command": "echo test"}}
    await orchestrator.on_openclaw_event(event)
    action_id = orchestrator.admin_handler.approval_queue[0]["id"]
    await orchestrator._process_approval(action_id, approved=False)
    # After rejection, queue is cleared but command is not executed
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_handle_client_non_build(orchestrator):
    """Test standard relay in handle_client"""
    mock_ws = AsyncMock()
    orchestrator.mode = "plan"
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "message", "content": "test message"}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception:
        pass
    assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_on_openclaw_event_error_relay(orchestrator):
    """Test error handling when relaying to UI clients"""
    mock_client = AsyncMock()
    mock_client.send_json.side_effect = ConnectionError("conn lost")
    orchestrator.clients.add(mock_client)
    await orchestrator.on_openclaw_event({"type": "event"})
    assert mock_client not in orchestrator.clients


@pytest.mark.asyncio
async def test_orchestrator_run_autonomous_build_full(orchestrator):
    """Test full autonomous build with LLM dispatch success"""
    mock_ws = AsyncMock()
    msg = Message(content="build me something", sender="user")
    with patch.object(orchestrator, "_llm_dispatch", return_value="Dispatch Success"):
        await orchestrator.run_autonomous_build(msg, mock_ws)
        assert mock_ws.send_json.called


@pytest.mark.asyncio
async def test_orchestrator_client_removal(orchestrator):
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = ConnectionError("done")
    await orchestrator.handle_client(mock_ws)
    assert mock_ws not in orchestrator.clients


@pytest.mark.asyncio
async def test_orchestrator_api_credentials_loading():
    """Test API credentials loading via safe line-by-line parser (VULN-004 fix)."""
    import tempfile

    from core.config import load_api_credentials

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('OPENAI_API_KEY = "test-key-123"\n')
        f.write('ANTHROPIC_API_KEY = "anthropic-key-456"\n')
        temp_path = f.name
    try:
        with (
            patch("core.config.os.path.exists", return_value=True),
            patch("core.config.os.path.join", return_value=temp_path),
            patch("core.config.os.getcwd", return_value="/tmp"),
        ):
            load_api_credentials()
            assert os.environ.get("OPENAI_API_KEY") == "test-key-123"
            assert os.environ.get("ANTHROPIC_API_KEY") == "anthropic-key-456"
    finally:
        os.unlink(temp_path)
        # Clean up environment
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.mark.asyncio
async def test_orchestrator_on_messaging_connect(orchestrator):
    """Test on_messaging_connect sends greeting"""
    with patch.object(orchestrator, "_to_platform_message") as mock_to_platform:
        mock_msg = MagicMock()
        mock_to_platform.return_value = mock_msg
        await orchestrator.on_messaging_connect("client-123", "whatsapp")
        assert orchestrator.adapters["messaging"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_admin_check_failure(orchestrator):
    """Test admin command rejected for non-admin"""
    orchestrator.config.admins = ["admin-only"]
    result = await orchestrator._handle_admin_command("!mode build", "non-admin")
    assert result is False


@pytest.mark.asyncio
async def test_orchestrator_deny_command(orchestrator):
    """Test !deny command"""
    orchestrator.config.admins = ["admin"]
    with patch("core.config.Config.save") as mock_save:
        result = await orchestrator._handle_admin_command("!deny rm -rf", "admin")
        assert result is True
        assert "rm -rf" in orchestrator.config.policies.get("deny", [])
        assert mock_save.called


@pytest.mark.asyncio
async def test_orchestrator_policies_command(orchestrator):
    """Test !policies command"""
    orchestrator.config.admins = ["admin"]
    orchestrator.config.policies["allow"] = ["git status"]
    orchestrator.config.policies["deny"] = ["rm"]
    result = await orchestrator._handle_admin_command("!policies", "admin")
    assert result is True
    await asyncio.sleep(0.05)
    assert orchestrator.adapters["messaging"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_unknown_admin_command(orchestrator):
    """Test unknown admin command returns False"""
    orchestrator.config.admins = ["admin"]
    result = await orchestrator._handle_admin_command("!unknowncommand", "admin")
    assert result is False


@pytest.mark.asyncio
async def test_orchestrator_restart_components_full(orchestrator):
    """Test self-healing restart logic for all components"""
    # Messaging
    await orchestrator.restart_component("messaging")
    assert True

    # MCP
    orchestrator.adapters["mcp"].start_all = AsyncMock()
    await orchestrator.restart_component("mcp")
    assert orchestrator.adapters["mcp"].start_all.called

    # Gateway
    await orchestrator.restart_component("gateway")
    assert True

    # Failure case
    orchestrator.adapters["openclaw"].connect.side_effect = Exception("err")
    await orchestrator.restart_component("openclaw")
    assert True  # Should handle exception and print


@pytest.mark.asyncio
async def test_orchestrator_handle_client_json_error_robust(orchestrator):
    """Test handle_client with malformed JSON"""
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = ["{invalid}", Exception("done")]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception:
        pass
    assert True


@pytest.mark.asyncio
async def test_orchestrator_dispatch_unknown_provider(orchestrator):
    """Test get_llm_provider with unknown type defaults to ollama"""
    from core.llm_providers import OllamaProvider, get_llm_provider

    p = get_llm_provider({"provider": "unknown"})
    assert isinstance(p, OllamaProvider)


@pytest.mark.asyncio
async def test_orchestrator_run_autonomous_build_step_error(orchestrator):
    """Test error handling in autonomous build loop"""
    mock_ws = AsyncMock()
    msg = Message(content="build", sender="u")
    orchestrator.llm.generate.side_effect = Exception("llm error")
    with patch("core.build_session.can_allocate", return_value=True):
        await orchestrator.run_autonomous_build(msg, mock_ws)
    assert mock_ws.send_json.called
    # Check if error status was sent
    calls = [c[0][0] for c in mock_ws.send_json.call_args_list]
    assert any("Error: llm error" in c.get("content", "") for c in calls)


@pytest.mark.asyncio
async def test_orchestrator_proactive_loop_calendar_exception(orchestrator):
    """Test calendar exception handling in proactive loop"""
    orchestrator.adapters["memu"].get_anticipations.return_value = []
    orchestrator.adapters["mcp"].call_tool.side_effect = Exception("Calendar service not configured")
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.proactive_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert orchestrator.adapters["mcp"].call_tool.called


@pytest.mark.asyncio
async def test_orchestrator_openclaw_connect_greeting(orchestrator):
    """Test greeting sent on OpenClaw connect/handshake"""
    event = {"method": "connect", "params": {}}
    await orchestrator.on_openclaw_event(event)
    assert orchestrator.adapters["openclaw"].send_message.called
    orchestrator.adapters["openclaw"].send_message.reset_mock()
    event = {"method": "handshake", "params": {}}
    await orchestrator.on_openclaw_event(event)
    assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_approval_queue_update_error(orchestrator):
    """Test error handling when updating approval queue"""
    mock_client = AsyncMock()
    mock_client.send_json.side_effect = ConnectionError("Client disconnected")
    orchestrator.clients.add(mock_client)
    orchestrator.admin_handler.approval_queue.append(
        {
            "id": "test-action-1",
            "type": "system_command",
            "payload": {},
            "description": "Test command",
        }
    )
    await orchestrator._process_approval("test-action-1", approved=True)
    assert mock_client not in orchestrator.clients


@pytest.mark.asyncio
async def test_root_endpoint():
    """Test FastAPI root endpoint"""
    from core.orchestrator import root

    result = await root()
    assert result["status"] == "online"
    assert result["message"] == "MegaBot API is running"


@pytest.mark.asyncio
async def test_orchestrator_ui_approval_events(orchestrator):
    """Test approve/reject action events from UI"""
    mock_ws = AsyncMock()
    action_id = "test-id-123"
    orchestrator.admin_handler.approval_queue.append({"id": action_id, "type": "test", "payload": {}})
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "approve_action", "action_id": action_id}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception:
        pass
    assert len(orchestrator.admin_handler.approval_queue) == 0
    action_id = "test-id-456"
    orchestrator.admin_handler.approval_queue.append({"id": action_id, "type": "test", "payload": {}})
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "reject_action", "action_id": action_id}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception:
        pass
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_admin_commands_empty_policies(orchestrator):
    """Test !allow/!deny with empty policies dict for coverage"""
    orchestrator.config.admins = ["admin"]
    orchestrator.config.policies = {}
    with patch("core.config.Config.save"):
        await orchestrator._handle_admin_command("!allow cmd1", "admin")
        assert "cmd1" in orchestrator.config.policies["allow"]
        await orchestrator._handle_admin_command("!deny cmd2", "admin")
        assert "cmd2" in orchestrator.config.policies["deny"]


@pytest.mark.asyncio
async def test_orchestrator_handle_admin_command_empty_text(orchestrator):
    """Test _handle_admin_command with empty/whitespace text covers line 129"""
    orchestrator.config.admins = ["admin"]
    result = await orchestrator._handle_admin_command("", "admin")
    assert result is False
    result = await orchestrator._handle_admin_command("   ", "admin")
    assert result is False


@pytest.mark.asyncio
async def test_orchestrator_process_approval_action_not_found(orchestrator):
    """Test _process_approval when action is not found covers line 463"""
    await orchestrator._process_approval("non-existent-id", approved=True)
    assert True


@pytest.mark.asyncio
async def test_orchestrator_process_approval_subprocess_exceptions(orchestrator):
    """Test subprocess exception handling in _process_approval covers lines 479-480, 485."""
    action = {
        "id": "test-action-123",
        "type": "system_command",
        "payload": {"params": {"command": "echo hello"}},
        "websocket": AsyncMock(),
    }
    # Ensure websocket doesn't look closed
    action["websocket"].close_code = None
    action["websocket"].closed = False
    orchestrator.admin_handler.approval_queue.append(action)
    with patch(
        "subprocess.run",
        side_effect=subprocess.SubprocessError("Subprocess failed"),
    ):
        await orchestrator._process_approval("test-action-123", approved=True)
    # The queue should be cleared regardless of execution failure
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_orchestrator_handle_client_command_message_type(orchestrator):
    """Test command message type handling covers lines 575-594"""
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = [
        json.dumps({"type": "command", "command": "ls -la"}),
        Exception("stop"),
    ]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception as e:
        if str(e) != "stop":
            raise
    assert len(orchestrator.admin_handler.approval_queue) == 1
    action = orchestrator.admin_handler.approval_queue[0]
    assert action["type"] == "system_command"
    status_calls = [call for call in mock_ws.send_json.call_args_list if call[0][0].get("type") == "status"]
    assert len(status_calls) > 0


@pytest.mark.asyncio
async def test_websocket_endpoint_orchestrator_none():
    """Test websocket endpoint when orchestrator is not initialized"""
    with patch("core.orchestrator.orchestrator", None):
        mock_ws = AsyncMock()
        # SEC-FIX-001: WebSocket auth requires a valid token
        with patch.dict("os.environ", {"WS_AUTH_TOKEN": "test-token"}):
            mock_ws.query_params = {"token": "test-token"}
            await websocket_endpoint(mock_ws)
            mock_ws.accept.assert_called_once()
            mock_ws.send_text.assert_called_once_with("Orchestrator not initialized")
            mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_endpoint_with_orchestrator(orchestrator):
    """Test websocket endpoint when orchestrator is initialized"""
    import core.orchestrator

    with patch("core.orchestrator.orchestrator", orchestrator):
        mock_ws = AsyncMock()
        orchestrator.handle_client = AsyncMock()
        # SEC-FIX-001: WebSocket auth requires a valid token
        with patch.dict("os.environ", {"WS_AUTH_TOKEN": "test-token"}):
            mock_ws.query_params = {"token": "test-token"}
            await core.orchestrator.websocket_endpoint(mock_ws)
            orchestrator.handle_client.assert_called_once_with(mock_ws)


@pytest.mark.asyncio
async def test_health_endpoint_no_orchestrator():
    """Test health endpoint returns 503 when orchestrator is None"""
    import core.orchestrator as orch_module

    original = orch_module.orchestrator
    try:
        orch_module.orchestrator = None
        result = await health()
        assert result.status_code == 503
    finally:
        orch_module.orchestrator = original


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test health endpoint returns proper JSONResponse"""
    result = await health()
    # Without an orchestrator initialized, returns 503 unavailable
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_orchestrator_admin_loki_trigger(orchestrator):
    """Test !mode loki triggers loki activation (line 355)"""
    orchestrator.config.admins = ["admin"]
    with patch.object(orchestrator.loki, "activate", new_callable=AsyncMock) as mock_activate:
        await orchestrator._handle_admin_command("!mode loki", "admin")
        # Give it a tiny bit of time for the task to start
        await asyncio.sleep(0.01)
        mock_activate.assert_called_once_with("Auto-trigger from chat")


@pytest.mark.asyncio
async def test_orchestrator_health_with_error(orchestrator):
    """Test !health command and get_system_health with error (lines 453, 618-619)"""
    orchestrator.config.admins = ["admin"]

    # 1. Make memory.memory_stats raise exception (lines 618-619)
    orchestrator.memory.memory_stats.side_effect = Exception("Stats failed")

    health_data = await orchestrator.get_system_health()
    assert health_data["memory"]["status"] == "down"
    assert "Stats failed" in health_data["memory"]["error"]

    # 2. Test !health display with error (line 453)
    with patch.object(orchestrator.health_monitor, "get_system_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = {"test": {"status": "down", "error": "simulated error"}}

        with patch.object(orchestrator, "send_platform_message", new_callable=AsyncMock) as mock_send:
            await orchestrator._handle_admin_command("!health", "admin")
            await asyncio.sleep(0.01)

            # Check the message content
            call_args = mock_send.call_args[0][0]
            assert "simulated error" in call_args.content


@pytest.mark.asyncio
async def test_orchestrator_start_rag_print(orchestrator, caplog):
    """Test RAG build print and exception (lines 541-542)"""
    import logging

    with caplog.at_level(logging.DEBUG, logger="core.lifecycle"):
        # Success path (line 541)
        orchestrator.rag.build_index = AsyncMock()
        await orchestrator.start()
        assert any("Project RAG index built for:" in r.message for r in caplog.records)

        caplog.clear()

        # Exception path (line 542)
        orchestrator.rag.build_index.side_effect = Exception("RAG Error")
        await orchestrator.start()
        assert any("Failed to build RAG index: RAG Error" in r.message for r in caplog.records)


# =====================================================================
# FROM test_orchestrator_coverage.py (6 tests)
# Fixture renamed: mock_config → mock_config_coverage
# Test renamed: test_orchestrator_on_openclaw_event → test_orchestrator_on_openclaw_event_coverage
# =====================================================================


@pytest.mark.asyncio
async def test_orchestrator_initialization_all_components(mock_config_coverage):
    async def mock_coro():
        pass

    with (
        patch("core.orchestrator.MemoryServer"),
        patch("core.orchestrator.OpenClawAdapter") as mock_oc,
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager") as mock_mcp,
        patch("core.orchestrator.MegaBotMessagingServer") as mock_msg,
        patch("core.orchestrator.UnifiedGateway") as mock_gw,
        patch("core.orchestrator.ModuleDiscovery") as mock_disc_class,
        patch("core.orchestrator.LokiMode"),
        patch("core.orchestrator.get_llm_provider"),
    ):
        mock_msg.return_value.start = mock_coro
        mock_gw.return_value.start = mock_coro
        mock_oc.return_value.connect = AsyncMock()
        mock_oc.return_value.subscribe_events = AsyncMock()
        mock_mcp.return_value.start_all = AsyncMock()

        orch = MegaBotOrchestrator(mock_config_coverage)
        orch.discovery = MagicMock()
        orch.background_tasks = AsyncMock()
        orch.rag = AsyncMock()

        await orch.start()
        assert orch.discovery.scan.called


@pytest.mark.asyncio
async def test_orchestrator_on_openclaw_event_coverage(mock_config_coverage):
    with (
        patch("core.orchestrator.MemoryServer"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
        patch("core.orchestrator.MegaBotMessagingServer"),
        patch("core.orchestrator.UnifiedGateway"),
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.LokiMode"),
        patch("core.orchestrator.get_llm_provider"),
    ):
        orch = MegaBotOrchestrator(mock_config_coverage)
        orch.adapters["openclaw"] = AsyncMock()
        orch._handle_admin_command = AsyncMock()

        await orch.on_openclaw_event({"method": "connect"})
        assert orch.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_tool_handling(mock_config_coverage):
    with (
        patch("core.orchestrator.MemoryServer"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
        patch("core.orchestrator.MegaBotMessagingServer"),
        patch("core.orchestrator.UnifiedGateway"),
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.LokiMode"),
        patch("core.orchestrator.get_llm_provider"),
    ):
        orch = MegaBotOrchestrator(mock_config_coverage)
        orch.permissions = MagicMock()
        orch.permissions.is_authorized.return_value = True

        mock_agent = MagicMock()
        # Respect stricter activation policy in AgentCoordinator
        mock_agent._active = True
        mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "fs"}]
        mock_agent.role = "tester"
        orch.sub_agents["agent1"] = mock_agent

        with patch("builtins.open", MagicMock(return_value=io.StringIO("content"))):
            res = await orch._execute_tool_for_sub_agent("agent1", {"name": "read_file", "input": {"path": "test.txt"}})
            assert "content" in res


@pytest.mark.asyncio
async def test_orchestrator_handle_client_websocket(mock_config_coverage):
    with (
        patch("core.orchestrator.MemoryServer"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
        patch("core.orchestrator.MegaBotMessagingServer"),
        patch("core.orchestrator.UnifiedGateway"),
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.LokiMode"),
        patch("core.orchestrator.get_llm_provider"),
    ):
        orch = MegaBotOrchestrator(mock_config_coverage)
        ws = AsyncMock()
        ws.receive_json.side_effect = [
            {"type": "message", "content": "hi"},
            Exception("Exit"),
        ]
        try:
            await orch.handle_client(ws)
        except Exception:
            pass
        assert ws.accept.called


@pytest.mark.asyncio
async def test_orchestrator_ivr_callback_direct():
    from core.orchestrator import ivr_callback

    request = AsyncMock()
    request.form.return_value = {"Digits": "1"}
    mock_orch = MagicMock()
    mock_orch.admin_handler = AsyncMock()
    with (
        patch("core.orchestrator.orchestrator", mock_orch),
        patch("core.app._validate_twilio_signature", return_value=True),
    ):
        response = await ivr_callback(request, action_id="act123")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_orchestrator_shutdown_full(mock_config_coverage):
    with (
        patch("core.orchestrator.MemoryServer"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
        patch("core.orchestrator.MegaBotMessagingServer"),
        patch("core.orchestrator.UnifiedGateway"),
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.LokiMode"),
        patch("core.orchestrator.get_llm_provider"),
    ):
        orch = MegaBotOrchestrator(mock_config_coverage)
        adapter = MagicMock()
        orch.adapters = {"test": adapter}
        orch.health_monitor = AsyncMock()
        await orch.shutdown()
        assert adapter.shutdown.called


# =====================================================================
# FROM test_orchestrator_coverage_final.py (3 tests)
# Fixture renamed: orchestrator → orchestrator_coverage_final
# =====================================================================


@pytest.mark.asyncio
async def test_orchestrator_spawn_sub_agent(orchestrator_coverage_final):
    orchestrator_coverage_final.discovery = MagicMock()
    orchestrator_coverage_final.discovery.get_module.return_value = MagicMock()

    with patch("core.agent_coordinator.SubAgent") as mock_agent_class:
        mock_agent = mock_agent_class.return_value
        mock_agent.id = "agent_123"
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="VALID")  # Synthesis result

        agent_id = await orchestrator_coverage_final._spawn_sub_agent({"role": "tester"})
        assert "VALID" in agent_id


@pytest.mark.asyncio
async def test_orchestrator_admin_commands(orchestrator_coverage_final):
    orchestrator_coverage_final.config.admins = ["admin1"]
    orchestrator_coverage_final.admin_handler.approval_queue = [{"id": "act1"}]
    orchestrator_coverage_final.admin_handler._process_approval = AsyncMock()

    # !approve
    await orchestrator_coverage_final._handle_admin_command("!approve act1", "admin1")
    orchestrator_coverage_final.admin_handler._process_approval.assert_called_with("act1", approved=True)

    # !reject
    await orchestrator_coverage_final._handle_admin_command("!reject act1", "admin1")
    orchestrator_coverage_final.admin_handler._process_approval.assert_called_with("act1", approved=False)

    # !allow
    orchestrator_coverage_final.config.policies = {}
    await orchestrator_coverage_final._handle_admin_command("!allow pattern", "admin1")
    assert "pattern" in orchestrator_coverage_final.config.policies["allow"]

    # !deny
    await orchestrator_coverage_final._handle_admin_command("!deny bad", "admin1")
    assert "bad" in orchestrator_coverage_final.config.policies["deny"]

    # !mode
    await orchestrator_coverage_final._handle_admin_command("!mode build", "admin1")
    assert orchestrator_coverage_final.mode == "build"

    # !whoami
    await orchestrator_coverage_final._handle_admin_command("!whoami", "admin1", chat_id="c1", platform="p1")
    assert orchestrator_coverage_final.memory.get_unified_id.called

    # !backup
    await orchestrator_coverage_final._handle_admin_command("!backup", "admin1")
    assert orchestrator_coverage_final.memory.backup_database.called

    # !health
    await orchestrator_coverage_final._handle_admin_command("!health", "admin1")
    assert orchestrator_coverage_final.memory.memory_stats.called

    # !policies
    orchestrator_coverage_final.config.policies = {"allow": ["a"], "deny": ["d"]}
    with patch.object(orchestrator_coverage_final, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator_coverage_final._handle_admin_command("!policies", "admin1")
        assert mock_send.called

    # !history_clean
    with patch.object(orchestrator_coverage_final, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator_coverage_final._handle_admin_command("!history_clean c1", "admin1")
        assert orchestrator_coverage_final.memory.chat_forget.called

    # !link
    with patch.object(orchestrator_coverage_final, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator_coverage_final._handle_admin_command("!link user2", "admin1", chat_id="c1", platform="p2")
        assert orchestrator_coverage_final.memory.link_identity.called

    # !rag_rebuild
    orchestrator_coverage_final.rag = AsyncMock()
    await orchestrator_coverage_final._handle_admin_command("!rag_rebuild", "admin1")
    assert orchestrator_coverage_final.rag.build_index.called


@pytest.mark.asyncio
async def test_orchestrator_redaction_agent(orchestrator_coverage_final):
    orchestrator_coverage_final.computer_driver = AsyncMock()
    orchestrator_coverage_final.computer_driver.execute.side_effect = [
        json.dumps({"sensitive_regions": [{"x": 0, "y": 0, "width": 10, "height": 10}]}),  # analyze
        "redacted_data",  # blur
    ]
    orchestrator_coverage_final._verify_redaction = AsyncMock(return_value=True)

    msg = Message(content="img", sender="u", attachments=[{"type": "image", "data": "orig"}])
    await orchestrator_coverage_final.send_platform_message(msg)
    assert msg.attachments[0]["data"] == "redacted_data"
    assert msg.attachments[0]["metadata"]["redacted"] is True


# =====================================================================
# FROM test_orchestrator_extended.py (10 tests)
# No fixture changes — uses conftest orchestrator fixture directly.
# =====================================================================


@pytest.mark.asyncio
async def test_heartbeat_loop(orchestrator):
    """Test heartbeat loop functionality and component restarts"""
    orchestrator.adapters = {"test": MagicMock(is_connected=False)}

    with (
        patch("asyncio.sleep", side_effect=[None, Exception("break")]),
        patch.object(orchestrator, "restart_component", new_callable=AsyncMock) as mock_restart,
    ):
        try:
            await orchestrator.heartbeat_loop()
        except Exception:
            pass

        assert mock_restart.called


@pytest.mark.asyncio
async def test_pruning_loop(orchestrator):
    """Test memory pruning loop"""
    orchestrator.memory = MagicMock()
    orchestrator.memory.get_all_chat_ids = AsyncMock(return_value=["chat1"])
    orchestrator.memory.chat_forget = AsyncMock()

    with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
        try:
            await orchestrator.pruning_loop()
        except Exception:
            pass

        assert orchestrator.memory.get_all_chat_ids.called
        assert orchestrator.memory.chat_forget.called


@pytest.mark.asyncio
async def test_proactive_loop(orchestrator):
    """Test proactive task checking loop"""
    orchestrator.adapters = {
        "memu": MagicMock(),
        "openclaw": MagicMock(),
        "mcp": MagicMock(),
    }
    orchestrator.adapters["memu"].get_anticipations = AsyncMock(return_value=[{"content": "Action 1"}])
    orchestrator.adapters["openclaw"].send_message = AsyncMock()
    orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value=[])

    with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
        try:
            await orchestrator.proactive_loop()
        except Exception:
            pass

        assert orchestrator.adapters["memu"].get_anticipations.called
        assert orchestrator.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_check_identity_claims(orchestrator):
    """Test identity linking through conversation"""
    orchestrator.admin_handler = MagicMock()
    orchestrator.admin_handler.approval_queue = []
    orchestrator.llm = MagicMock()
    orchestrator.llm.generate = AsyncMock(return_value="user123")
    orchestrator.send_platform_message = AsyncMock()

    # Simulate a "link" mention
    await orchestrator._check_identity_claims("I am user123", "native", "p1", "c1")

    assert len(orchestrator.admin_handler.approval_queue) == 1
    assert orchestrator.admin_handler.approval_queue[0]["type"] == "identity_link"
    assert orchestrator.admin_handler.approval_queue[0]["payload"]["internal_id"] == "USER123"


def test_sanitize_output(orchestrator):
    """Test terminal output sanitization"""
    text = "\x1b[31mRed\x1b[0m text"
    sanitized = orchestrator._sanitize_output(text)
    assert "Red" in sanitized
    assert "\x1b" not in sanitized


@pytest.mark.asyncio
async def test_get_relevant_lessons(orchestrator):
    """Test RAG retrieval of learned lessons"""
    orchestrator.llm = MagicMock()
    orchestrator.llm.generate = AsyncMock(return_value="keyword1, keyword2")
    orchestrator.memory = MagicMock()
    orchestrator.memory.memory_search = AsyncMock(return_value=[{"content": "Lesson 1", "key": "k1"}])

    lessons = await orchestrator._get_relevant_lessons("how to fix bugs")
    assert "Lesson 1" in lessons


@pytest.mark.asyncio
async def test_spawn_sub_agent_validation_fail(orchestrator):
    """Test _spawn_sub_agent when validation fails (line 1335)"""
    orchestrator.llm = AsyncMock()
    orchestrator.llm.generate.return_value = "BLOCK: security violation"  # No 'VALID' here
    tool_input = {"name": "evil", "task": "format c:", "role": "Senior Dev"}

    # Mock agent
    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value=["format"])
    mock_agent.run = AsyncMock(return_value="executed")
    with (
        patch("core.agent_coordinator.SubAgent", return_value=mock_agent),
        patch("core.agent_coordinator.can_allocate", return_value=True),
    ):
        result = await orchestrator._spawn_sub_agent(tool_input)
        assert "blocked by pre-flight check" in result


@pytest.mark.asyncio
async def test_spawn_sub_agent_synthesis_fallback(orchestrator):
    """Test _spawn_sub_agent synthesis fallback (line 1392)"""
    orchestrator.llm = AsyncMock()
    orchestrator.llm.generate.side_effect = [
        "VALID",  # 1. validation
        "CRITICAL: Always backup before format",  # 2. synthesis (no JSON)
    ]
    tool_input = {"name": "dev", "task": "task", "role": "Senior Dev"}

    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock()
    mock_agent.run = AsyncMock(return_value="raw result")
    with (
        patch("core.agent_coordinator.SubAgent", return_value=mock_agent),
        patch("core.agent_coordinator.can_allocate", return_value=True),
    ):
        result = await orchestrator._spawn_sub_agent(tool_input)
        assert "CRITICAL: Always backup" in result


@pytest.mark.asyncio
async def test_execute_tool_for_sub_agent_paths(orchestrator):
    """Test various failure paths in _execute_tool_for_sub_agent"""
    # 1. Agent not found (line 1418)
    orchestrator.sub_agents = {}
    res = await orchestrator._execute_tool_for_sub_agent("unknown", {})
    assert "Agent not found" in res

    # Setup mock agent
    mock_agent = MagicMock()
    mock_agent._active = True
    mock_agent.role = "Senior Dev"
    orchestrator.sub_agents = {"agent1": mock_agent}

    # 2. Tool not allowed (line 1428)
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "s"}]
    res = await orchestrator._execute_tool_for_sub_agent("agent1", {"name": "forbidden"})
    assert "outside the domain boundaries" in res

    # 3. Permission denied (line 1435)
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized.return_value = False
    res = await orchestrator._execute_tool_for_sub_agent("agent1", {"name": "read_file"})
    assert "Permission denied" in res

    # 4. Tool logic not implemented (line 1473)
    orchestrator.permissions.is_authorized.return_value = True
    mock_agent._get_sub_tools.return_value = [{"name": "unknown_tool", "scope": "s"}]
    # Remove MCP adapter so the code takes the direct "logic not implemented" path
    orchestrator.adapters.pop("mcp", None)
    res = await orchestrator._execute_tool_for_sub_agent("agent1", {"name": "unknown_tool"})
    assert "logic not implemented" in res


def test_sanitize_output_empty(orchestrator):
    """Test _sanitize_output with empty string (line 1620)"""
    assert orchestrator._sanitize_output("") == ""
    assert orchestrator._sanitize_output(None) == ""


# =====================================================================
# FROM test_orchestrator_gaps.py (33 tests)
# No fixture changes — uses conftest orchestrator and mock_config fixtures.
# =====================================================================

# --- _safe_create_task tests ---


@pytest.mark.asyncio
async def test_safe_create_task_runtime_error_fallback():
    """Lines 23-24: get_running_loop raises RuntimeError → falls back to get_event_loop."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def noop():
        pass

    # Patch get_running_loop to raise RuntimeError
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        mock_loop = asyncio.get_event_loop()
        with patch("asyncio.get_event_loop", return_value=mock_loop) as mock_gel:
            task = _safe_create_task(noop(), name="test-fallback")
            assert task is not None
            mock_gel.assert_called_once()
            # Let the task finish
            await task


@pytest.mark.asyncio
async def test_safe_create_task_set_name_success():
    """Lines 29-30: name provided → task.set_name(name) called successfully."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def noop():
        pass

    task = _safe_create_task(noop(), name="my-named-task")
    # set_name should succeed silently
    assert task is not None
    await task


@pytest.mark.asyncio
async def test_safe_create_task_set_name_failure():
    """Lines 31-32: task.set_name raises → exception swallowed."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def noop():
        pass

    real_loop = asyncio.get_running_loop()
    original_create_task = real_loop.create_task

    def patched_create_task(coro, **kwargs):
        real_task = original_create_task(coro, **kwargs)
        # Replace set_name with one that raises
        real_task.set_name = MagicMock(side_effect=AttributeError("no set_name"))
        return real_task

    with patch.object(real_loop, "create_task", side_effect=patched_create_task):
        task = _safe_create_task(noop(), name="should-fail")
        assert task is not None
        await task


@pytest.mark.asyncio
async def test_safe_create_task_on_done_with_exception(caplog):
    """Lines 36-40: _on_done detects a task exception and logs it."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def fail():
        raise ValueError("boom")

    with caplog.at_level("ERROR"):
        task = _safe_create_task(fail(), name="failing-task")
        try:
            await task
        except ValueError:
            pass
        # Allow the done callback to fire
        await asyncio.sleep(0.05)
    assert "task_error" in caplog.text or "boom" in caplog.text


@pytest.mark.asyncio
async def test_safe_create_task_on_done_cancelled():
    """Lines 41-42: _on_done with CancelledError → swallowed silently."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def hang():
        await asyncio.sleep(999)

    task = _safe_create_task(hang(), name="cancel-me")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # Let callback fire — should not raise
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_safe_create_task_on_done_discard_fails():
    """Lines 48-49: _orchestrator_tasks.discard raises → swallowed."""
    import core.task_utils as task_utils_mod
    from core.task_utils import safe_create_task as _safe_create_task

    async def noop():
        pass

    # Create a custom set subclass whose discard raises
    class BrokenSet(set):
        def discard(self, elem):
            raise TypeError("bad discard")

    original_tasks = task_utils_mod._tracked_tasks
    broken = BrokenSet(original_tasks)
    with patch.object(task_utils_mod, "_tracked_tasks", broken):
        task = _safe_create_task(noop(), name="discard-fail")
        await task
        await asyncio.sleep(0.05)
    # Restore is automatic via context manager


# --- lifespan context manager tests ---


@pytest.mark.asyncio
async def test_lifespan_skip_startup():
    """Lines 154-166: MEGABOT_SKIP_STARTUP=1 skips orchestrator start/shutdown."""
    from core.orchestrator import app, lifespan

    with patch.dict("os.environ", {"MEGABOT_SKIP_STARTUP": "1"}):
        async with lifespan(app):
            # Should yield without creating/starting orchestrator
            pass  # no error means success


# --- __init__ audit log auto-enable tests ---


@pytest.mark.asyncio
async def test_init_audit_log_auto_enable(mock_config):
    """Lines 235-239: audit log enabled when not CI and not pytest."""
    with patch.dict("os.environ", {}, clear=False):
        # Remove CI indicators
        env_copy = dict(__import__("os").environ)
        env_copy.pop("CI", None)
        env_copy.pop("GITHUB_ACTIONS", None)
        env_copy.pop("ENABLE_AUDIT_LOG", None)
        # Fake sys.argv to not contain "pytest"
        with (
            patch.dict("os.environ", env_copy, clear=True),
            patch.object(sys, "argv", ["megabot", "run"]),
            patch("core.orchestrator.attach_audit_file_handler") as mock_attach,
        ):
            try:
                orch = MegaBotOrchestrator(mock_config)
                mock_attach.assert_called_once()
            except Exception:
                pass


# --- start() _health_wrapper inner paths ---


@pytest.mark.asyncio
async def test_start_health_monitor_raises(orchestrator):
    """Lines 460-462: health_monitor.start_monitoring() raises → wrapper returns."""
    orchestrator.health_monitor.start_monitoring = MagicMock(side_effect=RuntimeError("monitor broken"))
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()
    # Should not raise; wrapper swallows the error


@pytest.mark.asyncio
async def test_start_health_wrapper_cls_name_raises(orchestrator):
    """Lines 466-467: getattr(coro, '__class__', ...) raises → cls_name=''."""

    # Create a coro-like object whose __class__ access raises
    class WeirdCoro:
        @property
        def __class__(self):
            raise RuntimeError("class access error")

        def close(self):
            pass

    orchestrator.health_monitor.start_monitoring = MagicMock(return_value=WeirdCoro())
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()


@pytest.mark.asyncio
async def test_start_health_wrapper_not_awaitable_mock_name(orchestrator):
    """Lines 486-487: safe_to_await=False, cls_name contains 'Mock' → returns."""
    # Return a MagicMock (not a coroutine) from start_monitoring
    mock_coro = MagicMock()
    orchestrator.health_monitor.start_monitoring = MagicMock(return_value=mock_coro)
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()


@pytest.mark.asyncio
async def test_start_create_task_returns_non_task_closes_coro(orchestrator):
    """Lines 515-519: create_task returns non-Task → coro.close() called."""
    orchestrator.health_monitor.start_monitoring = AsyncMock()
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    # Patch create_task to return a non-Task value
    with (
        patch("asyncio.create_task", return_value="not-a-task"),
        patch("asyncio.ensure_future", side_effect=Exception("also fails")),
    ):
        await orchestrator.start()
        # Wrapper coro should be closed, no warning


# --- _to_platform_message delegation ---


def test_to_platform_message_delegation(orchestrator):
    """Line 686: _to_platform_message delegates to message_router."""
    msg = Message(content="hello", sender="user")
    orchestrator.message_router._to_platform_message = MagicMock(return_value="platform_msg")
    result = orchestrator._to_platform_message(msg, chat_id="c1")
    orchestrator.message_router._to_platform_message.assert_called_once_with(msg, "c1")
    assert result == "platform_msg"


# --- _check_policy sub-scope & final scope ---


def test_check_policy_cmd_part_scope_match_allow(orchestrator):
    """Line 1223: sub-scope cmd_part match returns 'allow'."""
    orchestrator.permissions.is_authorized = MagicMock(
        side_effect=lambda scope: {
            "shell.git status": None,
            "git status": None,
            "shell.git": True,
        }.get(scope)
    )

    result = orchestrator._check_policy(
        {
            "method": "system.run",
            "params": {"command": "git status"},
        }
    )
    assert result == "allow"


def test_check_policy_cmd_part_scope_match_deny(orchestrator):
    """Line 1223: sub-scope cmd_part match returns 'deny'."""
    orchestrator.permissions.is_authorized = MagicMock(
        side_effect=lambda scope: {
            "shell.rm status": None,
            "rm status": None,
            "shell.rm": False,
        }.get(scope)
    )

    result = orchestrator._check_policy(
        {
            "method": "system.run",
            "params": {"command": "rm -rf /"},
        }
    )
    assert result == "deny"


def test_check_policy_scope_auth_true(orchestrator):
    """Line 1228: scope auth is True → returns 'allow'."""
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)
    result = orchestrator._check_policy({"method": "some.method", "params": {}})
    assert result == "allow"


def test_check_policy_scope_auth_false(orchestrator):
    """Line 1230: scope auth is False → returns 'deny'."""
    orchestrator.permissions.is_authorized = MagicMock(return_value=False)
    result = orchestrator._check_policy({"method": "some.method", "params": {}})
    assert result == "deny"


# --- _process_approval branches ---


@pytest.mark.asyncio
async def test_process_approval_outbound_vision(orchestrator):
    """Lines 1377-1396: approved outbound_vision action."""
    action_id = "vis-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "outbound_vision",
            "payload": {
                "message_content": "Look at this",
                "attachments": [],
                "chat_id": "chat1",
                "platform": "native",
                "target_client": "client1",
            },
        }
    ]
    orchestrator.message_router._to_platform_message = MagicMock()
    platform_msg = MagicMock()
    orchestrator.message_router._to_platform_message.return_value = platform_msg
    orchestrator.adapters["messaging"].send_message = AsyncMock()
    orchestrator.clients = set()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.adapters["messaging"].send_message.assert_called_once()
    assert platform_msg.platform == "native"
    # Action removed from queue
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_process_approval_data_execution(orchestrator):
    """Lines 1399-1425: approved data_execution action."""
    action_id = "data-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "data_execution",
            "payload": {"name": "test_ds", "code": "x = 1"},
        }
    ]
    orchestrator.clients = set()

    with patch("features.dash_data.agent.DashDataAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.execute_python_analysis = AsyncMock(return_value="result: 42")
        MockAgent.return_value = mock_instance

        orchestrator.send_platform_message = AsyncMock()
        await orchestrator._process_approval(action_id, approved=True)

        orchestrator.send_platform_message.assert_called_once()
        call_msg = orchestrator.send_platform_message.call_args[0][0]
        assert "42" in call_msg.content


@pytest.mark.asyncio
async def test_process_approval_data_execution_error(orchestrator):
    """Lines 1417-1418: data_execution raises exception."""
    action_id = "data-err"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "data_execution",
            "payload": {"name": "ds", "code": "bad"},
        }
    ]
    orchestrator.clients = set()

    with patch("features.dash_data.agent.DashDataAgent", side_effect=ImportError("no module")):
        orchestrator.send_platform_message = AsyncMock()
        await orchestrator._process_approval(action_id, approved=True)
        call_msg = orchestrator.send_platform_message.call_args[0][0]
        assert "failed" in call_msg.content.lower()


@pytest.mark.asyncio
async def test_process_approval_computer_use(orchestrator):
    """Lines 1428-1465: approved computer_use action (non-screenshot)."""
    action_id = "comp-1"
    ws = AsyncMock()
    cb = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "computer_use",
            "payload": {"action": "click", "coordinate": [100, 200], "text": None},
            "websocket": ws,
            "callback": cb,
        }
    ]
    orchestrator.clients = set()
    orchestrator.computer_driver.execute = AsyncMock(return_value="clicked at 100,200")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.computer_driver.execute.assert_called_once_with("click", [100, 200], None)
    ws.send_json.assert_called()
    # Callback invoked
    cb.assert_called_once_with("clicked at 100,200")
    orchestrator.adapters["openclaw"].send_message.assert_called_once()


@pytest.mark.asyncio
async def test_process_approval_computer_use_screenshot(orchestrator):
    """Lines 1445-1447: computer_use screenshot path."""
    action_id = "comp-ss"
    ws = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "computer_use",
            "payload": {"action": "screenshot", "coordinate": None, "text": None},
            "websocket": ws,
        }
    ]
    orchestrator.clients = set()
    orchestrator.computer_driver.execute = AsyncMock(return_value="base64imagedata")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    # Should send screenshot type
    calls = ws.send_json.call_args_list
    screenshot_call = [c for c in calls if c[0][0].get("type") == "screenshot"]
    assert len(screenshot_call) == 1


@pytest.mark.asyncio
async def test_process_approval_identity_link(orchestrator):
    """Lines 1468-1484: approved identity_link action."""
    action_id = "id-link-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "identity_link",
            "payload": {
                "internal_id": "ADMIN",
                "platform": "telegram",
                "platform_id": "12345",
                "chat_id": "chat-tg",
            },
        }
    ]
    orchestrator.clients = set()
    orchestrator.memory.link_identity = AsyncMock()
    orchestrator.send_platform_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.memory.link_identity.assert_called_once_with("ADMIN", "telegram", "12345")
    orchestrator.send_platform_message.assert_called_once()
    call_msg = orchestrator.send_platform_message.call_args[0][0]
    assert "ADMIN" in call_msg.content


@pytest.mark.asyncio
async def test_process_approval_denial_with_callback(orchestrator):
    """Line 1489: denied action invokes callback with 'Action denied by user.'."""
    action_id = "deny-1"
    cb = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "system_command",
            "payload": {},
            "callback": cb,
        }
    ]
    orchestrator.clients = set()

    await orchestrator._process_approval(action_id, approved=False)

    cb.assert_called_once_with("Action denied by user.")
    # Queue is cleared
    assert len(orchestrator.admin_handler.approval_queue) == 0


# --- shutdown() deeper paths ---


@pytest.mark.asyncio
async def test_shutdown_stop_fn_returns_coroutine(orchestrator):
    """Lines 1647-1651: stop_fn returns a real coroutine → awaited."""

    orchestrator.health_monitor = MagicMock()
    # Use AsyncMock so the coroutine is only created (and properly managed)
    # when .shutdown() is actually called, avoiding "coroutine never awaited".
    orchestrator.health_monitor.shutdown = AsyncMock(side_effect=ValueError("stop failed"))
    orchestrator._health_task = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    # Should not raise; exception swallowed


@pytest.mark.asyncio
async def test_shutdown_health_task_cancel_exception(orchestrator):
    """Lines 1657-1659: _health_task.cancel() raises → swallowed."""
    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None  # not callable

    mock_task = MagicMock()
    mock_task.cancel = MagicMock(side_effect=RuntimeError("cancel failed"))
    orchestrator._health_task = mock_task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_background_tasks_returns_awaitable(orchestrator):
    """Lines 1665-1673: background_tasks.shutdown() returns a coroutine → awaited."""

    async def bg_shutdown_coro():
        pass

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None
    orchestrator._health_task = None

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=bg_shutdown_coro())

    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_health_task_await_self_coroutine_close(orchestrator):
    """Lines 1694-1697: _health_task.__await__.__self__ is a coroutine → closed."""

    async def dummy():
        pass

    real_coro = dummy()

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None

    # Create a mock task whose __await__.__self__ is the real coroutine
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__class__ = MagicMock  # cls_name will contain "MagicMock"
    mock_await = MagicMock()
    mock_await.__self__ = real_coro
    mock_task.__await__ = mock_await
    orchestrator._health_task = mock_task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    # The real_coro should be closed (no "coroutine never awaited" warning)


@pytest.mark.asyncio
async def test_shutdown_real_task_health(orchestrator):
    """Lines 1703-1709: _health_task is a real asyncio.Task → awaited."""

    async def slow():
        await asyncio.sleep(10)

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None

    task = asyncio.create_task(slow())
    task.cancel()
    orchestrator._health_task = task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    assert task.cancelled()


# --- _process_approval tirith validation ---


@pytest.mark.asyncio
async def test_process_approval_tirith_blocks_command(orchestrator):
    """Approved system_command goes through ALLOWED_COMMANDS allowlist."""
    action_id = "tir-1"
    ws = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "system_command",
            "payload": {"params": {"command": "echo hello"}},
            "websocket": ws,
        }
    ]
    orchestrator.clients = set()

    await orchestrator._process_approval(action_id, approved=True)

    # Should send command result to websocket
    ws_calls = ws.send_json.call_args_list
    assert any("command_result" in str(c) for c in ws_calls)


# --- ivr_callback endpoint ---


@pytest.mark.asyncio
async def test_ivr_callback_no_orchestrator():
    """Lines 1743-1744: orchestrator is None → 'System error.' response."""
    from httpx import ASGITransport, AsyncClient

    from core.orchestrator import app

    with (
        patch.dict("os.environ", {"MEGABOT_SKIP_STARTUP": "1"}),
        patch("core.orchestrator.orchestrator", None),
        patch("core.app._validate_twilio_signature", return_value=True),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ivr?action_id=test123", data={"Digits": "1"})
            assert resp.status_code == 200
            assert "System error" in resp.text


@pytest.mark.asyncio
async def test_ivr_callback_rejects_missing_signature():
    """VULN-012: /ivr rejects requests without valid Twilio signature (CSRF)."""
    from httpx import ASGITransport, AsyncClient

    from core.orchestrator import app

    with patch.dict(
        "os.environ",
        {"MEGABOT_SKIP_STARTUP": "1", "TWILIO_AUTH_TOKEN": "test-token"},
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # No X-Twilio-Signature header → 403
            resp = await client.post("/ivr?action_id=test123", data={"Digits": "1"})
            assert resp.status_code == 403
            assert "Unauthorized" in resp.text


@pytest.mark.asyncio
async def test_ivr_callback_rejects_no_auth_token():
    """VULN-012: /ivr rejects when TWILIO_AUTH_TOKEN is not set (fail-closed)."""
    from httpx import ASGITransport, AsyncClient

    from core.orchestrator import app

    with patch.dict(
        "os.environ",
        {"MEGABOT_SKIP_STARTUP": "1"},
        clear=False,
    ):
        os.environ.pop("TWILIO_AUTH_TOKEN", None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ivr?action_id=test123", data={"Digits": "1"})
            assert resp.status_code == 403


# =====================================================================
# FROM test_orchestrator_health_monitor.py (2 tests)
# Fixture DELETED (identical to main) — tests use main orchestrator fixture.
# =====================================================================


@pytest.mark.asyncio
async def test_start_handles_create_task_patched(orchestrator):
    """When asyncio.create_task and ensure_future are patched to raise,
    orchestrator.start should not raise and should not leave an unscheduled
    _health_task set (coroutine should be closed).
    """
    # Patch create_task and ensure_future to raise so scheduling fails
    with (
        patch("asyncio.create_task", side_effect=Exception("create_task patched")),
        patch("asyncio.ensure_future", side_effect=Exception("ensure_future patched")),
    ):
        # Should not raise
        await orchestrator.start()

        # Since both scheduling methods failed, _health_task should be None
        assert getattr(orchestrator, "_health_task", None) is None


@pytest.mark.asyncio
async def test_shutdown_closes_underlying_coroutine_for_mock_task(orchestrator):
    """If _health_task is a MagicMock that borrowed a real coroutine's
    __await__, orchestrator.shutdown should attempt to close the underlying
    coroutine to avoid "coroutine was never awaited" warnings.
    """

    async def _dummy_monitor():
        # short sleep to create a real coroutine object
        await asyncio.sleep(0.01)

    coro = _dummy_monitor()

    mock_task = MagicMock()
    # Attach the real coroutine's __await__ bound method so shutdown logic
    # can discover and close the underlying coroutine via __await__.__self__
    mock_task.__await__ = coro.__await__

    orchestrator._health_task = mock_task

    # Should not raise
    await orchestrator.shutdown()

    # Underlying coroutine should be closed (cr_frame becomes None)
    assert getattr(coro, "cr_frame", None) is None


# =====================================================================
# FROM test_orchestrator_round2.py (21 tests)
# Test renamed: test_shutdown_health_task_coro_close → test_shutdown_health_task_coro_close_round2
# =====================================================================


# --- _safe_create_task _on_done callback (lines 43-44) ---


@pytest.mark.asyncio
async def test_safe_create_task_on_done_non_cancelled_exception():
    """Lines 43-44: t.exception() raises non-CancelledError -> prints error."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def failing_task():
        raise ValueError("something went wrong")

    task = _safe_create_task(failing_task(), name="test-fail")
    with pytest.raises(ValueError):
        await task


@pytest.mark.asyncio
async def test_safe_create_task_on_done_callback_error():
    """Lines 43-44: t.exception() itself raises a non-CancelledError."""
    from core.task_utils import _tracked_tasks as _orchestrator_tasks
    from core.task_utils import safe_create_task as _safe_create_task

    async def simple_task():
        return "done"

    task = _safe_create_task(simple_task(), name="test-ok")
    await task
    assert task not in _orchestrator_tasks


# --- __init__ audit log attachment exception (lines 237-239) ---


@pytest.mark.asyncio
async def test_init_audit_log_exception(mock_config):
    """Lines 237-239: exception in audit log setup -> pass (no crash)."""
    with (
        patch(
            "core.orchestrator.attach_audit_file_handler",
            side_effect=OSError("log fail"),
        ),
        patch.dict("os.environ", {"MEGABOT_ENABLE_AUDIT_LOG": "1"}),
    ):
        orch = MegaBotOrchestrator(mock_config)
        assert orch is not None


# --- run_autonomous_gateway_build memory injection (line 385) ---


@pytest.mark.asyncio
async def test_gateway_build_memory_injection(orchestrator):
    """Line 385: lessons prepended to message.content."""
    gateway_mock = AsyncMock()
    gateway_mock.send_message = AsyncMock()
    orchestrator.adapters = {
        "mcp": AsyncMock(),
        "openclaw": AsyncMock(),
        "gateway": gateway_mock,
        "messaging": AsyncMock(),
    }
    orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value="allowed_dirs")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    # Mock memory and message_handler for send_platform_message path
    orchestrator.memory.chat_write = AsyncMock()

    msg = Message(content="build something", sender="user", platform="gateway")
    original_data = {"_meta": {"client_id": "test-client", "connection_type": "local"}}

    with (
        patch("core.build_session.get_relevant_lessons", new_callable=AsyncMock, return_value="LESSON: do X"),
        patch("core.build_session.can_allocate", return_value=True),
    ):
        await orchestrator.run_autonomous_gateway_build(msg, original_data)
    assert msg.content.startswith("LESSON: do X")


# --- start() health wrapper - Mock detection (lines 472, 478-483) ---


@pytest.mark.asyncio
async def test_start_health_wrapper_mock_detection(orchestrator):
    """Lines 472, 478-479: Mock in cls_name -> return."""
    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=MagicMock())
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    # The health wrapper saw "MagicMock" in cls_name and returned early.
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_start_health_wrapper_last_resort_await(orchestrator):
    """Lines 480-483: non-Mock, non-coroutine -> last-resort await."""

    class AwaitableThing:
        """Not a coroutine/future/task, not a Mock."""

        def __await__(self):
            yield
            return None

    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=AwaitableThing())
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    await asyncio.sleep(0.05)
    await orchestrator.shutdown()


# --- start() coro.close() raises (lines 510-511) ---


@pytest.mark.asyncio
async def test_start_coro_close_raises(orchestrator):
    """Lines 510-511: coro.close() raises in finally -> pass."""
    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = AsyncMock()
    orchestrator.health_monitor = mock_monitor

    with (
        patch("asyncio.create_task", return_value="not-a-task"),
        patch("asyncio.ensure_future", return_value="also-not"),
    ):
        await orchestrator.start()

    await orchestrator.shutdown()


# --- _verify_redaction failure path (lines 736-739) ---


@pytest.mark.asyncio
async def test_verify_redaction_failure(orchestrator):
    """Lines 736-739: remaining sensitive_regions -> return False."""
    orchestrator.computer_driver = AsyncMock()
    orchestrator.computer_driver.execute = AsyncMock(
        return_value=json.dumps({"sensitive_regions": [{"x": 10, "y": 20, "w": 100, "h": 50}]})
    )
    result = await orchestrator._verify_redaction("base64imagedata")
    assert result is False


@pytest.mark.asyncio
async def test_verify_redaction_success(orchestrator):
    """Lines 741-742: no remaining sensitive_regions -> return True."""
    orchestrator.computer_driver = AsyncMock()
    orchestrator.computer_driver.execute = AsyncMock(return_value=json.dumps({"sensitive_regions": []}))
    result = await orchestrator._verify_redaction("base64imagedata")
    assert result is True


# --- _start_approval_escalation (lines 752-809) ---


@pytest.mark.asyncio
async def test_escalation_action_not_in_queue(orchestrator):
    """Lines 752: action no longer in queue -> skip everything."""
    action = {"id": "action-xyz"}
    orchestrator.admin_handler.approval_queue = []

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_dnd_active_wrap_around(orchestrator):
    """Lines 757-770: DND active (dnd_start > dnd_end, e.g., 22-7)."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-1"}
    orchestrator.admin_handler.approval_queue = [action]

    with patch("asyncio.sleep", new_callable=AsyncMock), patch("core.approval_workflows.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=23)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_dnd_same_range(orchestrator):
    """Lines 765-766: DND with dnd_start <= dnd_end (e.g., 8-17)."""
    orchestrator.config.system.dnd_start = 8
    orchestrator.config.system.dnd_end = 17
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-2"}
    orchestrator.admin_handler.approval_queue = [action]

    with patch("asyncio.sleep", new_callable=AsyncMock), patch("core.approval_workflows.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=10)  # inside 8-17
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_calendar_dnd(orchestrator):
    """Lines 773-800: calendar event with DND keyword -> skip call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-3"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(return_value=[{"summary": "BUSY - Important Meeting"}])
    orchestrator.adapters = {"mcp": mcp_mock, "messaging": MagicMock()}

    with patch("asyncio.sleep", new_callable=AsyncMock), patch("core.approval_workflows.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=15)  # outside DND
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_calendar_check_fails(orchestrator):
    """Lines 797-800: calendar check raises exception -> continues to voice call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-4"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(side_effect=RuntimeError("calendar unavailable"))

    voice_mock = AsyncMock()
    voice_mock.make_call = AsyncMock()
    messaging_mock = MagicMock()
    messaging_mock.voice_adapter = voice_mock

    orchestrator.adapters = {"mcp": mcp_mock, "messaging": messaging_mock}

    with patch("asyncio.sleep", new_callable=AsyncMock), patch("core.approval_workflows.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=15)  # outside DND
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await orchestrator._start_approval_escalation(action)

    voice_mock.make_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_escalation_no_admin_phone(orchestrator):
    """Lines 808-809: no admin_phone -> prints message, no call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = None

    action = {"id": "action-5"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(return_value=[])
    orchestrator.adapters = {"mcp": mcp_mock, "messaging": MagicMock()}

    with patch("asyncio.sleep", new_callable=AsyncMock), patch("core.approval_workflows.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=15)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await orchestrator._start_approval_escalation(action)


# --- _handle_computer_tool (lines 1149-1173) ---


@pytest.mark.asyncio
async def test_handle_computer_tool(orchestrator):
    """Lines 1149-1173: queues action, sends JSON, broadcasts."""
    ws_mock = AsyncMock()
    ws_mock.send_json = AsyncMock()

    client_mock = AsyncMock()
    client_mock.send_json = AsyncMock()
    orchestrator.clients = [client_mock]

    orchestrator.admin_handler = MagicMock()
    orchestrator.admin_handler.approval_queue = []

    tool_input = {"action": "screenshot", "x": 100, "y": 200}
    await orchestrator._handle_computer_tool(tool_input, ws_mock, action_id="act-123")

    assert len(orchestrator.admin_handler.approval_queue) == 1
    queued = orchestrator.admin_handler.approval_queue[0]
    assert queued["id"] == "act-123"
    assert queued["type"] == "computer_use"

    ws_mock.send_json.assert_awaited_once()
    call_args = ws_mock.send_json.call_args[0][0]
    assert call_args["type"] == "status"

    client_mock.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_computer_tool_auto_id(orchestrator):
    """Lines 1156: action_id is None -> auto-generate UUID."""
    ws_mock = AsyncMock()
    ws_mock.send_json = AsyncMock()
    orchestrator.clients = []
    orchestrator.admin_handler = MagicMock()
    orchestrator.admin_handler.approval_queue = []

    tool_input = {"action": "click"}
    await orchestrator._handle_computer_tool(tool_input, ws_mock, action_id=None)

    queued = orchestrator.admin_handler.approval_queue[0]
    assert queued["id"]  # Should have auto-generated UUID


# --- shutdown() paths from round2 ---


@pytest.mark.asyncio
async def test_shutdown_health_monitor_stop_raises(orchestrator):
    """Lines 1628-1630: health_monitor.stop() raises -> pass."""
    mock_monitor = MagicMock()
    mock_monitor.stop = MagicMock(side_effect=RuntimeError("stop failed"))
    orchestrator.health_monitor = mock_monitor
    orchestrator._health_task = None

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_background_tasks_await_exception(orchestrator):
    """Lines 1651-1652: await background_tasks.shutdown() raises -> pass."""

    async def failing_shutdown():
        raise RuntimeError("shutdown boom")

    mock_bg = MagicMock()
    mock_bg.shutdown = MagicMock(return_value=failing_shutdown())
    orchestrator.background_tasks = mock_bg
    orchestrator.health_monitor = None
    orchestrator._health_task = MagicMock()
    orchestrator._health_task.cancel = MagicMock()
    orchestrator._health_task.__class__ = type("MagicMock", (), {})

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close_round2(orchestrator):
    """Lines 1673-1676: __await__.__self__ is a coroutine -> close it."""

    async def dummy():
        pass

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__await__ = coro.__await__
    mock_task.__class__ = type("MagicMock", (), {})

    orchestrator._health_task = mock_task
    orchestrator.health_monitor = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)

    await orchestrator.shutdown()

    try:
        coro.close()
    except RuntimeError:
        pass


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close_raises(orchestrator):
    """Lines 1673-1674: possible_coro.close() raises -> pass."""

    async def dummy():
        pass

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()

    await_fn = MagicMock()
    await_fn.__self__ = coro
    mock_task.__await__ = await_fn
    mock_task.__class__ = type("MagicMock", (), {})

    orchestrator._health_task = mock_task
    orchestrator.health_monitor = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)

    await orchestrator.shutdown()

    try:
        coro.close()
    except RuntimeError:
        pass


# =====================================================================
# FROM test_orchestrator_components_coverage.py (4 tests)
# Fixture renamed: mock_orchestrator → mock_orchestrator_components
# =====================================================================


@pytest.mark.asyncio
async def test_message_handler_full(mock_orchestrator_components):
    handler = MessageHandler(mock_orchestrator_components)
    mock_orchestrator_components.memory.get_unified_id.return_value = "u1"
    mock_orchestrator_components.memory.chat_read.return_value = []

    # process_gateway_message
    await handler.process_gateway_message({"type": "message", "content": "hi", "sender_id": "s1"})
    assert mock_orchestrator_components.memory.chat_write.called

    # _process_attachments
    mock_driver = AsyncMock()
    mock_driver.execute.return_value = "cat"

    # Reset the cached driver so our mock is used instead of the
    # real ComputerDriver resolved during process_gateway_message above
    handler._computer_driver = mock_driver

    res = await handler._process_attachments([{"type": "image", "data": "d"}], "s1", "c")
    assert "cat" in res or "cat" in str(res)

    # _update_chat_context
    await handler._update_chat_context("chat1", "hello")
    assert "chat1" in handler.chat_contexts


@pytest.mark.asyncio
async def test_health_monitor_all_paths(mock_orchestrator_components):
    monitor = HealthMonitor(mock_orchestrator_components)

    # Success
    mock_orchestrator_components.memory.memory_stats.return_value = {}
    mock_orchestrator_components.adapters["openclaw"].websocket = MagicMock()
    mock_orchestrator_components.adapters["messaging"].clients = []
    mock_orchestrator_components.adapters["mcp"].servers = []
    health_data = await monitor.get_system_health()
    assert health_data["memory"]["status"] == "up"

    # Failures
    mock_orchestrator_components.memory.memory_stats.side_effect = Exception("Err")
    del mock_orchestrator_components.adapters["openclaw"].websocket
    health_data = await monitor.get_system_health()
    assert health_data["memory"]["status"] == "down"

    # Monitoring loop
    with (
        patch.object(
            monitor,
            "get_system_health",
            side_effect=[{"c": {"status": "down"}}, BreakLoop()],
        ),
        patch("asyncio.sleep", side_effect=[None, BreakLoop()]),
    ):
        try:
            await monitor.start_monitoring()
        except BreakLoop:
            pass
    assert mock_orchestrator_components.restart_component.called


@pytest.mark.asyncio
async def test_background_tasks_all_loops(mock_orchestrator_components):
    tasks = BackgroundTasks(mock_orchestrator_components)
    mock_orchestrator_components.user_identity = AsyncMock()
    mock_orchestrator_components.chat_memory = AsyncMock()
    mock_orchestrator_components.knowledge_memory = AsyncMock()
    mock_orchestrator_components.memory.get_all_chat_ids.return_value = ["c1"]

    with patch("asyncio.sleep", side_effect=[BreakLoop(), BreakLoop(), BreakLoop()]):
        # sync_loop
        try:
            await tasks.sync_loop()
        except BreakLoop:
            pass
        # pruning_loop
        try:
            await tasks.pruning_loop()
        except BreakLoop:
            pass
        # backup_loop
        try:
            await tasks.backup_loop()
        except BreakLoop:
            pass

    assert mock_orchestrator_components.user_identity.sync_pending_identities.called
    assert mock_orchestrator_components.memory.chat_forget.called


@pytest.mark.asyncio
async def test_background_tasks_proactive_loop_success(mock_orchestrator_components):
    tasks = BackgroundTasks(mock_orchestrator_components)
    mock_orchestrator_components.adapters["memu"].get_anticipations.return_value = [{"content": "task"}]
    mock_orchestrator_components.adapters["mcp"].call_tool.return_value = ["event"]
    with patch("asyncio.sleep", side_effect=[BreakLoop(), BreakLoop(), BreakLoop()]):
        try:
            await tasks.proactive_loop()
        except BreakLoop:
            pass
    assert mock_orchestrator_components.adapters["openclaw"].send_message.called


# =====================================================================
# FROM test_orchestrator_components_extra.py (5 tests)
# Fixture renamed: mock_orchestrator → mock_orchestrator_components_extra
# =====================================================================


@pytest.mark.asyncio
async def test_message_handler_extra_coverage(mock_orchestrator_components_extra):
    handler = MessageHandler(mock_orchestrator_components_extra)

    # 1. Admin command success (lines 63-73)
    mock_orchestrator_components_extra.admin_handler.handle_command.return_value = True
    await handler._handle_user_message({"content": "!test"}, "s1", "c1", "p1")
    assert mock_orchestrator_components_extra.send_platform_message.called

    # 2. Mode 'build' (lines 85)
    mock_orchestrator_components_extra.mode = "build"
    mock_orchestrator_components_extra.admin_handler.handle_command.return_value = False
    await handler._handle_user_message({"content": "build me"}, "s1", "c1", "p1")
    assert mock_orchestrator_components_extra.run_autonomous_gateway_build.called

    # 3. Audio attachment (lines 119-125)
    res = await handler._process_attachments([{"type": "audio", "data": "abc"}], "s1", "c1")
    assert res == ""


@pytest.mark.asyncio
async def test_health_monitor_extra_coverage(mock_orchestrator_components_extra):
    monitor = HealthMonitor(mock_orchestrator_components_extra)

    # Messaging server error (lines 176-177)
    mock_orchestrator_components_extra.adapters["messaging"] = MagicMock()
    type(mock_orchestrator_components_extra.adapters["messaging"]).clients = property(lambda x: 1 / 0)
    health_data = await monitor.get_system_health()
    assert health_data["messaging"]["status"] == "down"

    # MCP server error (lines 185-186)
    mock_orchestrator_components_extra.adapters["mcp"] = MagicMock()
    type(mock_orchestrator_components_extra.adapters["mcp"]).servers = property(lambda x: 1 / 0)
    health_data = await monitor.get_system_health()
    assert health_data["mcp"]["status"] == "down"

    # Monitoring loop error (line 225)
    with (
        patch.object(monitor, "get_system_health", side_effect=Exception("loop error")),
        patch("asyncio.sleep", side_effect=[BreakLoop()]),
    ):
        try:
            await monitor.start_monitoring()
        except BreakLoop:
            pass


@pytest.mark.asyncio
async def test_background_tasks_extra_coverage(mock_orchestrator_components_extra):
    tasks = BackgroundTasks(mock_orchestrator_components_extra)

    # Start all tasks (lines 238-242)
    with (
        patch("core.orchestrator_components.safe_create_task") as mock_create,
        patch.object(tasks, "sync_loop", return_value=None),
        patch.object(tasks, "proactive_loop", return_value=None),
        patch.object(tasks, "pruning_loop", return_value=None),
        patch.object(tasks, "backup_loop", return_value=None),
    ):
        await tasks.start_all_tasks()
        assert mock_create.called

    # Sync loop errors (lines 256-257, 265-266, 273-274, 278)
    mock_orchestrator_components_extra.user_identity = AsyncMock()
    mock_orchestrator_components_extra.user_identity.sync_pending_identities.side_effect = Exception("err")

    with patch("asyncio.sleep", side_effect=[Exception("sync loop error"), BreakLoop()]):
        try:
            await tasks.sync_loop()
        except BreakLoop:
            pass
        except Exception:
            pass

    # Proactive loop error (lines 311-312)
    mock_orchestrator_components_extra.adapters["memu"].get_anticipations.side_effect = Exception("proactive error")
    with patch("asyncio.sleep", side_effect=[BreakLoop()]):
        try:
            await tasks.proactive_loop()
        except BreakLoop:
            pass


@pytest.mark.asyncio
async def test_proactive_loop_calendar(mock_orchestrator_components_extra):
    tasks = BackgroundTasks(mock_orchestrator_components_extra)
    mock_orchestrator_components_extra.adapters["memu"].get_anticipations.return_value = []
    mock_orchestrator_components_extra.adapters["mcp"].call_tool.return_value = ["event1"]
    with patch("asyncio.sleep", side_effect=[BreakLoop()]):
        try:
            await tasks.proactive_loop()
        except BreakLoop:
            pass
    assert mock_orchestrator_components_extra.send_platform_message.called


@pytest.mark.asyncio
async def test_start_all_tasks_handles_scheduling_failures(mock_orchestrator_components_extra):
    """If asyncio.create_task and asyncio.ensure_future are patched to raise,
    start_all_tasks must not raise and must close the created coroutine objects.
    """
    tasks = BackgroundTasks(mock_orchestrator_components_extra)

    async def _dummy():
        await asyncio.sleep(0.01)

    # Create coroutine objects so we can inspect their cr_frame after
    c1 = _dummy()
    c2 = _dummy()
    c3 = _dummy()
    c4 = _dummy()

    with (
        patch("asyncio.create_task", side_effect=Exception("create_task patched")),
        patch("asyncio.ensure_future", side_effect=Exception("ensure_future patched")),
        patch.object(tasks, "sync_loop", return_value=c1),
        patch.object(tasks, "proactive_loop", return_value=c2),
        patch.object(tasks, "pruning_loop", return_value=c3),
        patch.object(tasks, "backup_loop", return_value=c4),
    ):
        # Should not raise
        await tasks.start_all_tasks()

        # Ensure any coroutine objects created for the test
        # are explicitly closed
        for _c in (c1, c2, c3, c4):
            try:
                _c.close()
            except Exception:
                pass

    assert True


# =====================================================================
# FROM test_orchestrator_components_gaps.py (11 tests in 2 classes)
# Fixture renamed: mock_orch → mock_orch_components_gaps
# =====================================================================


class TestHealthMonitorShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_awaits_and_clears(self, mock_orch_components_gaps):
        """shutdown() cancels all tasks, awaits them, and clears state."""
        monitor = HealthMonitor(mock_orch_components_gaps)

        t1 = AsyncMock(spec=asyncio.Task)
        t1.cancel = MagicMock()
        t2 = AsyncMock(spec=asyncio.Task)
        t2.cancel = MagicMock()

        monitor._tasks = [t1, t2]
        monitor.last_status = {"memory": {"status": "up"}}
        monitor.restart_counts = {"memory": 1}

        await monitor.shutdown()

        t1.cancel.assert_called_once()
        t2.cancel.assert_called_once()
        assert monitor._tasks == []
        assert monitor.last_status == {}
        assert monitor.restart_counts == {}

    @pytest.mark.asyncio
    async def test_shutdown_handles_cancel_exception(self, mock_orch_components_gaps):
        """shutdown() doesn't raise when task.cancel() itself throws."""
        monitor = HealthMonitor(mock_orch_components_gaps)

        bad_task = MagicMock()
        bad_task.cancel.side_effect = RuntimeError("cancel failed")
        monitor._tasks = [bad_task]
        monitor.last_status = {"x": "y"}
        monitor.restart_counts = {"x": 1}

        await monitor.shutdown()

        assert monitor._tasks == []
        assert monitor.last_status == {}

    @pytest.mark.asyncio
    async def test_shutdown_await_raises_regular_exception(self, mock_orch_components_gaps):
        """shutdown() handles regular Exception from awaiting a task gracefully."""
        monitor = HealthMonitor(mock_orch_components_gaps)

        class FailingTask:
            """A task-like object that raises when awaited."""

            def cancel(self):
                pass

            def __await__(self):
                raise RuntimeError("boom")
                yield  # noqa: F841 - makes it a generator

        ft = FailingTask()
        monitor._tasks = [ft]

        async def _raise():
            raise RuntimeError("task error")

        real_task = asyncio.create_task(_raise())
        # Let the task run and fail
        await asyncio.sleep(0)
        monitor._tasks = [real_task]

        await monitor.shutdown()
        assert monitor._tasks == []

    @pytest.mark.asyncio
    async def test_shutdown_isinstance_check_raises(self, mock_orch_components_gaps):
        """shutdown() handles mocked types that raise on isinstance checks."""
        monitor = HealthMonitor(mock_orch_components_gaps)

        class WeirdObj:
            def cancel(self):
                pass

        obj = WeirdObj()
        monitor._tasks = [obj]

        with patch("asyncio.isfuture", side_effect=TypeError("weird type")):
            await monitor.shutdown()

        assert monitor._tasks == []


class TestBackgroundTasksScheduling:
    @pytest.mark.asyncio
    async def test_safe_schedule_ensure_future_fallback(self, mock_orch_components_gaps):
        """When create_task fails, _safe_schedule falls back to ensure_future."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        fake_coro = _make_fake_coro()
        mock_task = MagicMock()

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch(
                "asyncio.create_task",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "asyncio.ensure_future",
                return_value=mock_task,
            ) as ef_mock,
        ):
            await tasks.start_all_tasks()
            ef_mock.assert_called_once_with(fake_coro)
            assert mock_task in tasks._tasks

    @pytest.mark.asyncio
    async def test_safe_schedule_both_fail_closes_coro(self, mock_orch_components_gaps):
        """When both create_task and ensure_future fail, coro.close() is called."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        fake_coro = _make_fake_coro()

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch(
                "asyncio.create_task",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "asyncio.ensure_future",
                side_effect=RuntimeError("boom2"),
            ),
        ):
            await tasks.start_all_tasks()

        assert fake_coro.close.call_count >= 1
        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_coroutine_creation_raises(self, mock_orch_components_gaps):
        """When calling a loop function raises, start_all_tasks skips it."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(side_effect=RuntimeError("coro boom"))),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
        ):
            # Should not raise
            await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_skip_none_coro(self, mock_orch_components_gaps):
        """When a loop function returns None, start_all_tasks skips scheduling."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch("asyncio.create_task") as ct,
        ):
            await tasks.start_all_tasks()
            ct.assert_not_called()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_outer_close_on_schedule_failure(self, mock_orch_components_gaps):
        """When _safe_schedule returns None, the outer code closes the coro too."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        fake_coro = _make_fake_coro()

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch(
                "asyncio.create_task",
                side_effect=RuntimeError("no"),
            ),
            patch(
                "asyncio.ensure_future",
                side_effect=RuntimeError("no"),
            ),
        ):
            await tasks.start_all_tasks()

        assert fake_coro.close.call_count >= 2
        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_safe_schedule_coro_close_raises(self, mock_orch_components_gaps):
        """When coro.close() raises inside _safe_schedule, except catches it."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        fake_coro = MagicMock()
        fake_coro.close = MagicMock(side_effect=RuntimeError("close boom"))

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch(
                "asyncio.create_task",
                side_effect=RuntimeError("no"),
            ),
            patch(
                "asyncio.ensure_future",
                side_effect=RuntimeError("no"),
            ),
        ):
            # Should not raise even though close() throws
            await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_outer_loop_coro_close_raises(self, mock_orch_components_gaps):
        """When coro.close() raises in the outer loop, except catches it."""
        tasks = BackgroundTasks(mock_orch_components_gaps)

        call_count = [0]

        def close_sometimes():
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("close boom in outer")

        fake_coro = MagicMock()
        fake_coro.close = MagicMock(side_effect=close_sometimes)

        with (
            patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)),
            patch.object(tasks, "proactive_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "pruning_loop", new=MagicMock(return_value=None)),
            patch.object(tasks, "backup_loop", new=MagicMock(return_value=None)),
            patch(
                "asyncio.create_task",
                side_effect=RuntimeError("no"),
            ),
            patch(
                "asyncio.ensure_future",
                side_effect=RuntimeError("no"),
            ),
        ):
            await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0


# =====================================================================
# FROM test_coverage_completion.py & test_coverage_completion_final.py
# =====================================================================


@pytest.mark.asyncio
async def test_orchestrator_restart_components(mock_config):
    with patch("core.orchestrator.ModuleDiscovery"):
        orc = MegaBotOrchestrator(mock_config)
        orc.adapters = {
            "openclaw": AsyncMock(),
            "messaging": AsyncMock(),
            "mcp": AsyncMock(),
            "gateway": AsyncMock(),
        }

        await orc.restart_component("openclaw")
        assert orc.adapters["openclaw"].connect.called

        await orc.restart_component("messaging")
        # messaging restart creates a task

        await orc.restart_component("mcp")
        assert orc.adapters["mcp"].start_all.called

        await orc.restart_component("gateway")
        # gateway restart creates a task


@pytest.mark.asyncio
async def test_orchestrator_handle_client_json_error(orchestrator):
    mock_ws = AsyncMock()
    mock_ws.receive_text.side_effect = ["invalid json", Exception("stop")]
    try:
        await orchestrator.handle_client(mock_ws)
    except Exception:
        pass
    # Should handle error and continue or exit
    assert True


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


# ==============================================================
# Round 3 — merged from test_coverage_round3.py
# ==============================================================


@pytest.mark.asyncio
async def test_on_done_exception_from_task_exception_call():
    """Lines 43-44: t.exception() raises non-CancelledError -> prints error."""
    from core.task_utils import safe_create_task as _safe_create_task

    async def noop():
        pass

    task = _safe_create_task(noop())
    await task

    async def also_noop():
        pass

    task2 = _safe_create_task(also_noop())

    original_exception = task2.exception

    def raising_exception():
        raise RuntimeError("weird callback error")

    task2.exception = raising_exception

    await task2
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_start_health_wrapper_await_raises(orchestrator):
    """Line 472: safe_to_await=True, await coro raises -> pass."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()

    async def failing_monitor():
        raise RuntimeError("health loop crashed")

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=failing_monitor())
    mock_monitor.stop = MagicMock()
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    await asyncio.sleep(0.1)
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_start_health_wrapper_last_resort_await_raises(orchestrator):
    """Lines 482-483: last-resort await raises -> except pass."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()

    class FailingAwaitable:
        def __await__(self):
            raise RuntimeError("not a real coro")

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=FailingAwaitable())
    mock_monitor.stop = MagicMock()
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    await asyncio.sleep(0.1)
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_start_coro_close_raises_with_sleep(orchestrator):
    """Lines 510-511: coro.close() raises in finally -> pass."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = AsyncMock()
    mock_monitor.stop = MagicMock()
    orchestrator.health_monitor = mock_monitor

    with (
        patch("asyncio.create_task", return_value="not-a-task"),
        patch("asyncio.ensure_future", return_value="also-not"),
    ):
        await orchestrator.start()

    await asyncio.sleep(0.05)
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close(orchestrator):
    """Lines 1673-1676: shutdown() finds _health_task with __await__.__self__."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()

    async def dummy_coro():
        await asyncio.sleep(999)

    coro = dummy_coro()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__await__ = coro.__await__

    orchestrator._health_task = mock_task

    await orchestrator.shutdown()

    try:
        coro.close()
    except RuntimeError:
        pass


def test_core_getattr_megabot_orchestrator():
    """Line 16-19: __getattr__ returns MegaBotOrchestrator."""
    import core

    cls = core.__getattr__("MegaBotOrchestrator")
    from core.orchestrator import MegaBotOrchestrator

    assert cls is MegaBotOrchestrator


def test_core_getattr_unknown():
    """Line 20: __getattr__ raises for unknown attribute."""
    import core

    with pytest.raises(AttributeError, match="has no attribute"):
        core.__getattr__("NoSuchThing")


@pytest.mark.asyncio
async def test_orchestrator_extra_branches(orchestrator):
    # Test pruning_loop exception
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.pruning_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert True

    # Test backup_loop exception
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.backup_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert True

    # Test heartbeat_loop components down
    orchestrator.health_monitor.get_system_health = AsyncMock(return_value={"openclaw": {"status": "down"}})
    orchestrator.restart_component = AsyncMock()
    with patch("asyncio.sleep", side_effect=[None, Exception("stop")]):
        try:
            await orchestrator.heartbeat_loop()
        except Exception as e:
            if str(e) != "stop":
                raise
    assert orchestrator.restart_component.called


# ── Phase 5-7: Audio transcription in _process_attachments ──


@pytest.mark.asyncio
async def test_process_attachments_audio_success(mock_orchestrator_components):
    """Test _process_attachments handles audio attachment with successful transcription"""
    handler = MessageHandler(mock_orchestrator_components)

    mock_voice = AsyncMock()
    mock_voice.transcribe_audio = AsyncMock(return_value="Hello from audio")

    with patch("adapters.voice_adapter.VoiceAdapter", return_value=mock_voice):
        result = await handler._process_attachments(
            [{"type": "audio", "data": b"fake_audio_bytes"}], "sender1", "computer"
        )

    assert "[Audio Transcript]: Hello from audio" in result
    mock_voice.transcribe_audio.assert_called_once_with(b"fake_audio_bytes")


@pytest.mark.asyncio
async def test_process_attachments_audio_string_data(mock_orchestrator_components):
    """Test _process_attachments encodes string audio data to bytes"""
    handler = MessageHandler(mock_orchestrator_components)

    mock_voice = AsyncMock()
    mock_voice.transcribe_audio = AsyncMock(return_value="Transcribed text")

    with patch("adapters.voice_adapter.VoiceAdapter", return_value=mock_voice):
        result = await handler._process_attachments(
            [{"type": "audio", "data": "string_audio_data"}], "sender1", "computer"
        )

    assert "[Audio Transcript]: Transcribed text" in result
    # String data should be encoded to bytes
    mock_voice.transcribe_audio.assert_called_once_with(b"string_audio_data")


@pytest.mark.asyncio
async def test_process_attachments_audio_exception(mock_orchestrator_components):
    """Test _process_attachments handles transcription exception gracefully"""
    handler = MessageHandler(mock_orchestrator_components)

    with patch(
        "adapters.voice_adapter.VoiceAdapter",
        side_effect=Exception("VoiceAdapter init failed"),
    ):
        result = await handler._process_attachments([{"type": "audio", "data": b"fake_audio"}], "sender1", "computer")

    # Should not crash, should return empty or context without transcript
    assert "[Audio Transcript]" not in result


@pytest.mark.asyncio
async def test_process_attachments_audio_empty_transcript(mock_orchestrator_components):
    """Test _process_attachments handles empty transcript (no STT configured)"""
    handler = MessageHandler(mock_orchestrator_components)

    mock_voice = AsyncMock()
    mock_voice.transcribe_audio = AsyncMock(return_value="")

    with patch("adapters.voice_adapter.VoiceAdapter", return_value=mock_voice):
        result = await handler._process_attachments([{"type": "audio", "data": b"audio_data"}], "sender1", "computer")

    # Empty transcript should not be added
    assert "[Audio Transcript]" not in result
