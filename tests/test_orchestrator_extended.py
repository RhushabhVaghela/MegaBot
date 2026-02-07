"""Extended tests for MegaBot orchestrator"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from core.orchestrator import MegaBotOrchestrator
from core.interfaces import Message


@pytest.mark.asyncio
async def test_heartbeat_loop(orchestrator):
    """Test heartbeat loop functionality and component restarts"""
    orchestrator.adapters = {"test": MagicMock(is_connected=False)}

    with patch("asyncio.sleep", side_effect=[None, Exception("break")]):
        with patch.object(
            orchestrator, "restart_component", new_callable=AsyncMock
        ) as mock_restart:
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
    orchestrator.adapters["memu"].get_anticipations = AsyncMock(
        return_value=[{"content": "Action 1"}]
    )
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
    assert (
        orchestrator.admin_handler.approval_queue[0]["payload"]["internal_id"]
        == "USER123"
    )


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
    orchestrator.memory.memory_search = AsyncMock(
        return_value=[{"content": "Lesson 1", "key": "k1"}]
    )

    lessons = await orchestrator._get_relevant_lessons("how to fix bugs")
    assert "Lesson 1" in lessons


@pytest.mark.asyncio
async def test_spawn_sub_agent_validation_fail(orchestrator):
    """Test _spawn_sub_agent when validation fails (line 1335)"""
    orchestrator.llm = AsyncMock()
    orchestrator.llm.generate.return_value = (
        "BLOCK: security violation"  # No 'VALID' here
    )
    tool_input = {"name": "evil", "task": "format c:", "role": "Senior Dev"}

    # Mock agent
    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value=["format"])
    mock_agent.run = AsyncMock(return_value="executed")
    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
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
    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
        result = await orchestrator._spawn_sub_agent(tool_input)
        assert "CRITICAL: Always backup" in result


@pytest.mark.asyncio
async def test_execute_tool_for_sub_agent_paths(orchestrator):
    """Test various failure paths in _execute_tool_for_sub_agent (lines 1418, 1428, 1435, 1473)"""
    # 1. Agent not found (line 1418)
    orchestrator.sub_agents = {}
    res = await orchestrator._execute_tool_for_sub_agent("unknown", {})
    assert "Agent not found" in res

    # Setup mock agent
    mock_agent = MagicMock()
    # Tests must mark mock agents active under the stricter activation policy
    mock_agent._active = True
    mock_agent.role = "Senior Dev"
    orchestrator.sub_agents = {"agent1": mock_agent}

    # 2. Tool not allowed (line 1428)
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "s"}]
    res = await orchestrator._execute_tool_for_sub_agent(
        "agent1", {"name": "forbidden"}
    )
    assert "outside the domain boundaries" in res

    # 3. Permission denied (line 1435)
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized.return_value = False
    res = await orchestrator._execute_tool_for_sub_agent(
        "agent1", {"name": "read_file"}
    )
    assert "Permission denied" in res

    # 4. Tool logic not implemented (line 1473)
    orchestrator.permissions.is_authorized.return_value = True
    mock_agent._get_sub_tools.return_value = [{"name": "unknown_tool", "scope": "s"}]
    res = await orchestrator._execute_tool_for_sub_agent(
        "agent1", {"name": "unknown_tool"}
    )
    assert "logic not implemented" in res


def test_sanitize_output_empty(orchestrator):
    """Test _sanitize_output with empty string (line 1620)"""
    assert orchestrator._sanitize_output("") == ""
    assert orchestrator._sanitize_output(None) == ""
