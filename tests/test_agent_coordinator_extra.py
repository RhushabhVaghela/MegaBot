import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_inactive_agent_blocked(orchestrator):
    """Ensure _execute_tool_for_sub_agent refuses execution for non-active agents."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "Assistant"
    mock_agent._get_sub_tools.return_value = [
        {"name": "read_file", "scope": "filesystem.read"}
    ]
    # Agent exists but not activated (no _active flag)
    orch.sub_agents = {"inactive": mock_agent}

    res = await coord._execute_tool_for_sub_agent(
        "inactive", {"name": "read_file", "input": {"path": "/tmp/does_not_matter"}}
    )
    assert "not active" in res


@pytest.mark.asyncio
async def test_read_file_denied_outside_workspace(orchestrator, tmp_path):
    """Reads outside of the configured workspace must be denied."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    # Prepare workspace and an outside file
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("top secret")

    # Point orchestrator workspace to our workspace
    orch.config.paths["workspaces"] = str(workspace)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [
        {"name": "read_file", "scope": "filesystem.read"}
    ]
    mock_agent._active = True

    orch.sub_agents = {"agent1": mock_agent}
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    res = await coord._execute_tool_for_sub_agent(
        "agent1", {"name": "read_file", "input": {"path": str(outside_file)}}
    )
    assert "outside workspace" in res or "read_file denied" in res


@pytest.mark.asyncio
async def test_write_file_symlink_denied(orchestrator, tmp_path):
    """Writes to symlinks (even inside workspace) should be denied."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("external")

    # create a symlink inside the workspace pointing to outside file
    link_path = workspace / "link.txt"
    link_path.symlink_to(target)

    orch.config.paths["workspaces"] = str(workspace)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [
        {"name": "write_file", "scope": "filesystem.write"}
    ]
    mock_agent._active = True

    orch.sub_agents = {"agent_fs": mock_agent}
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    res = await coord._execute_tool_for_sub_agent(
        "agent_fs",
        {"name": "write_file", "input": {"path": str(link_path), "content": "x"}},
    )
    assert "Symlink" in res or "symlink" in res


@pytest.mark.asyncio
async def test_permission_must_be_strict_true(orchestrator):
    """Only an explicit True from is_authorized should allow tool execution."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [
        {"name": "read_file", "scope": "filesystem.read"}
    ]
    mock_agent._active = True

    orch.sub_agents = {"a": mock_agent}
    orch.permissions = MagicMock()
    # Simulate a truthy-but-not-True value (e.g., permissive string). Should be denied.
    orch.permissions.is_authorized.return_value = "allowed"

    res = await coord._execute_tool_for_sub_agent(
        "a", {"name": "read_file", "input": {"path": "/tmp/x"}}
    )
    assert "Permission denied" in res
