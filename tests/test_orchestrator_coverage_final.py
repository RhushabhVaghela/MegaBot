import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from core.orchestrator import MegaBotOrchestrator
from core.interfaces import Message
from adapters.messaging.server import PlatformMessage, MessageType


@pytest.fixture
def orchestrator():
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


@pytest.mark.asyncio
async def test_orchestrator_spawn_sub_agent(orchestrator):
    orchestrator.discovery = MagicMock()
    orchestrator.discovery.get_module.return_value = MagicMock()

    with patch("core.agent_coordinator.SubAgent") as mock_agent_class:
        mock_agent = mock_agent_class.return_value
        mock_agent.id = "agent_123"
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="VALID")  # Synthesis result

        agent_id = await orchestrator._spawn_sub_agent({"role": "tester"})
        assert "VALID" in agent_id


@pytest.mark.asyncio
async def test_orchestrator_admin_commands(orchestrator):
    orchestrator.config.admins = ["admin1"]
    orchestrator.admin_handler.approval_queue = [{"id": "act1"}]
    orchestrator.admin_handler._process_approval = AsyncMock()

    # !approve
    await orchestrator._handle_admin_command("!approve act1", "admin1")
    orchestrator.admin_handler._process_approval.assert_called_with(
        "act1", approved=True
    )

    # !reject
    await orchestrator._handle_admin_command("!reject act1", "admin1")
    orchestrator.admin_handler._process_approval.assert_called_with(
        "act1", approved=False
    )

    # !allow
    orchestrator.config.policies = {}
    await orchestrator._handle_admin_command("!allow pattern", "admin1")
    assert "pattern" in orchestrator.config.policies["allow"]

    # !deny
    await orchestrator._handle_admin_command("!deny bad", "admin1")
    assert "bad" in orchestrator.config.policies["deny"]

    # !mode
    await orchestrator._handle_admin_command("!mode build", "admin1")
    assert orchestrator.mode == "build"

    # !whoami
    await orchestrator._handle_admin_command(
        "!whoami", "admin1", chat_id="c1", platform="p1"
    )
    assert orchestrator.memory.get_unified_id.called

    # !backup
    await orchestrator._handle_admin_command("!backup", "admin1")
    assert orchestrator.memory.backup_database.called

    # !health
    await orchestrator._handle_admin_command("!health", "admin1")
    assert orchestrator.memory.memory_stats.called

    # !policies
    orchestrator.config.policies = {"allow": ["a"], "deny": ["d"]}
    with patch.object(orchestrator, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator._handle_admin_command("!policies", "admin1")
        assert mock_send.called

    # !history_clean
    with patch.object(orchestrator, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator._handle_admin_command("!history_clean c1", "admin1")
        assert orchestrator.memory.chat_forget.called

    # !link
    with patch.object(orchestrator, "send_platform_message", AsyncMock()) as mock_send:
        await orchestrator._handle_admin_command(
            "!link user2", "admin1", chat_id="c1", platform="p2"
        )
        assert orchestrator.memory.link_identity.called

    # !rag_rebuild
    orchestrator.rag = AsyncMock()
    await orchestrator._handle_admin_command("!rag_rebuild", "admin1")
    assert orchestrator.rag.build_index.called


@pytest.mark.asyncio
async def test_orchestrator_redaction_agent(orchestrator):
    orchestrator.computer_driver = AsyncMock()
    orchestrator.computer_driver.execute.side_effect = [
        json.dumps(
            {"sensitive_regions": [{"x": 0, "y": 0, "width": 10, "height": 10}]}
        ),  # analyze
        "redacted_data",  # blur
    ]
    orchestrator._verify_redaction = AsyncMock(return_value=True)

    msg = Message(
        content="img", sender="u", attachments=[{"type": "image", "data": "orig"}]
    )
    await orchestrator.send_platform_message(msg)
    assert msg.attachments[0]["data"] == "redacted_data"
    assert msg.attachments[0]["metadata"]["redacted"] is True
