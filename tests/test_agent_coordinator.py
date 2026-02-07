import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_spawn_sub_agent_validation_fail(orchestrator):
    """AgentCoordinator should block sub-agent when pre-flight validation fails."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    # Prepare mocked SubAgent
    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value="do dangerous things")
    mock_agent.run = AsyncMock(return_value="raw result")

    # Patch orchestrator.SubAgent as some tests patch core.orchestrator.SubAgent
    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
        # LLM returns non-VALID -> blocked
        orch.llm = MagicMock()
        orch.llm.generate = AsyncMock(return_value="nope")
        res = await coord._spawn_sub_agent({"name": "a1", "task": "t1"})
        assert "blocked by pre-flight" in res


@pytest.mark.asyncio
async def test_spawn_sub_agent_synthesis_and_memory(orchestrator):
    """Successful spawn should synthesize and write a lesson to memory."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value="plan")
    mock_agent.run = AsyncMock(return_value="raw result")

    # Make LLM return VALID for preflight and a JSON block for synthesis
    orch.llm = MagicMock()
    # First call: validation
    orch.llm.generate = AsyncMock(
        side_effect=["VALID", '{"summary":"ok","learned_lesson":"CRITICAL: do X"}']
    )

    # Replace memory with a spy
    orch.memory = MagicMock()
    orch.memory.memory_write = AsyncMock()

    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
        res = await coord._spawn_sub_agent({"name": "a2", "task": "t2"})
        assert isinstance(res, str)
        # memory_write should be called with key containing agent name
        orch.memory.memory_write.assert_called()


@pytest.mark.asyncio
async def test_execute_tool_for_sub_agent_paths(orchestrator):
    """Test tool execution paths via AgentCoordinator."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    # 1. Agent not found
    orch.sub_agents = {}
    res = await coord._execute_tool_for_sub_agent("unknown", {})
    assert "Agent not found" in res

    # 2. Tool not allowed
    mock_agent = MagicMock()
    mock_agent.role = "tester"
    # New stricter activation policy: tests must mark mock agents as active
    mock_agent._active = True
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "fs"}]
    orch.sub_agents = {"agent1": mock_agent}
    res = await coord._execute_tool_for_sub_agent("agent1", {"name": "forbidden"})
    assert "outside the domain boundaries" in res

    # 3. Permission denied
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = False
    res = await coord._execute_tool_for_sub_agent("agent1", {"name": "read_file"})
    assert "Permission denied" in res

    # 4. Tool logic not implemented (no MCP available)
    orch.permissions.is_authorized.return_value = True
    mock_agent._get_sub_tools.return_value = [{"name": "unknown_tool", "scope": "s"}]
    orch.adapters.pop("mcp", None)
    res = await coord._execute_tool_for_sub_agent("agent1", {"name": "unknown_tool"})
    assert "logic not implemented" in res
