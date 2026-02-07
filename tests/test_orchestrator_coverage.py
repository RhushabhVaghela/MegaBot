import pytest
import io
from unittest.mock import MagicMock, AsyncMock, patch
from core.orchestrator import MegaBotOrchestrator, ivr_callback
from core.config import Config, SystemConfig, SecurityConfig, AdapterConfig


@pytest.fixture
def mock_config():
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


@pytest.mark.asyncio
async def test_orchestrator_initialization_all_components(mock_config):
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

        orch = MegaBotOrchestrator(mock_config)
        orch.discovery = MagicMock()
        orch.background_tasks = AsyncMock()
        orch.rag = AsyncMock()

        await orch.start()
        assert orch.discovery.scan.called


@pytest.mark.asyncio
async def test_orchestrator_on_openclaw_event(mock_config):
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
        orch = MegaBotOrchestrator(mock_config)
        orch.adapters["openclaw"] = AsyncMock()
        orch._handle_admin_command = AsyncMock()

        await orch.on_openclaw_event({"method": "connect"})
        assert orch.adapters["openclaw"].send_message.called


@pytest.mark.asyncio
async def test_orchestrator_tool_handling(mock_config):
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
        orch = MegaBotOrchestrator(mock_config)
        orch.permissions = MagicMock()
        orch.permissions.is_authorized.return_value = True

        mock_agent = MagicMock()
        # Respect stricter activation policy in AgentCoordinator
        mock_agent._active = True
        mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "fs"}]
        mock_agent.role = "tester"
        orch.sub_agents["agent1"] = mock_agent

        with patch("builtins.open", MagicMock(return_value=io.StringIO("content"))):
            res = await orch._execute_tool_for_sub_agent(
                "agent1", {"name": "read_file", "input": {"path": "test.txt"}}
            )
            assert "content" in res


@pytest.mark.asyncio
async def test_orchestrator_handle_client_websocket(mock_config):
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
        orch = MegaBotOrchestrator(mock_config)
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
    request = AsyncMock()
    request.form.return_value = {"Digits": "1"}
    mock_orch = MagicMock()
    mock_orch.admin_handler = AsyncMock()
    with patch("core.orchestrator.orchestrator", mock_orch):
        response = await ivr_callback(request, action_id="act123")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_orchestrator_shutdown_full(mock_config):
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
        orch = MegaBotOrchestrator(mock_config)
        adapter = MagicMock()
        orch.adapters = {"test": adapter}
        orch.health_monitor = AsyncMock()
        await orch.shutdown()
        assert adapter.shutdown.called
