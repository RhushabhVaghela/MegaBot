import errno
from types import SimpleNamespace
import os
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_read_file_symlink_error_os_open_eloop(orchestrator, tmp_path):
    """If os.open raises ELOOP we surface a symlink/permission error."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    # place workspace inside tmp_path so path resolution succeeds
    orch.config.paths["workspaces"] = str(tmp_path)

    coord = AgentCoordinator(orch)

    # prepare an active mock agent with read_file allowed
    mock_agent = MagicMock()
    mock_agent.role = "tester"
    mock_agent._active = True
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "fs"}]
    orch.sub_agents = {"a1": mock_agent}

    # ensure permissions allow
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    # create a real file so Path.resolve and is_symlink behave sensibly
    target = tmp_path / "f.txt"
    target.write_text("hello")

    # Patch os.open to raise ELOOP as if a symlink was detected at open time
    def _bad_open(path, flags):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links")

    # Use monkeypatch via pytest builtin fixture

    try:
        orig_open = os.open
        os.open = _bad_open
        res = await coord._execute_tool_for_sub_agent(
            "a1", {"name": "read_file", "input": {"path": str(target)}}
        )
    finally:
        os.open = orig_open

    assert "possible symlink" in res or "symlink" in res


@pytest.mark.asyncio
async def test_read_file_toctou_detected(orchestrator, tmp_path):
    """If the file identity changes between lstat and fstat we detect TOCTOU."""
    from core.agent_coordinator import AgentCoordinator

    orch = orchestrator
    orch.config.paths["workspaces"] = str(tmp_path)

    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "tester"
    mock_agent._active = True
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "fs"}]
    orch.sub_agents = {"a1": mock_agent}

    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    target = tmp_path / "f2.txt"
    target.write_text("data")

    # Create fake stat objects
    pre_stat = SimpleNamespace(st_ino=1, st_dev=1, st_size=4, st_mode=0)
    post_stat = SimpleNamespace(st_ino=2, st_dev=1, st_size=4, st_mode=0)

    # Patch os.lstat, os.open, os.fstat, os.read, os.close
    orig_lstat = os.lstat
    orig_open = os.open
    orig_fstat = os.fstat
    orig_read = os.read
    orig_close = os.close

    def _fake_lstat(path):
        return pre_stat

    def _fake_open(path, flags):
        # return a fake fd integer
        return 42

    def _fake_fstat(fd):
        return post_stat

    def _fake_read(fd, n):
        return b""

    def _fake_close(fd):
        return None

    try:
        os.lstat = _fake_lstat
        os.open = _fake_open
        os.fstat = _fake_fstat
        os.read = _fake_read
        os.close = _fake_close

        res = await coord._execute_tool_for_sub_agent(
            "a1", {"name": "read_file", "input": {"path": str(target)}}
        )
    finally:
        os.lstat = orig_lstat
        os.open = orig_open
        os.fstat = orig_fstat
        os.read = orig_read
        os.close = orig_close

    assert "TOCTOU" in res or "TOCTOU detected" in res
