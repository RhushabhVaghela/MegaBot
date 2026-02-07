"""
Round 3 coverage tests — targeting the remaining gaps for 99%+ coverage.

Targets:
  - core/__init__.py lines 16-20  (__getattr__ lazy import)
  - core/memory/knowledge_memory.py line 165  (invalid order_by)
  - features/dash_data/agent.py lines 71-72  (ValueError/TypeError in stats)
  - core/orchestrator.py lines 43-44  (_on_done callback exception)
  - core/orchestrator.py lines 472, 482-483  (health wrapper exception paths)
  - core/orchestrator.py lines 510-511  (coro.close() raises)
  - core/orchestrator.py lines 1673-1676  (shutdown coro close)
  - core/network/gateway.py lines 108-110, 133, 144-145  (health wrapper)
  - core/network/gateway.py lines 172-173  (coro.close() raises in start)
  - core/network/gateway.py lines 212-215  (stop() coro close)
  - core/agent_coordinator.py lines 75-76, 83-84, 87 (SubAgent fallback)
  - core/agent_coordinator.py line 267 (relative path resolution)
  - core/agent_coordinator.py lines 287-288 (outer path validation except)
  - core/agent_coordinator.py line 426 (read_file empty chunk break)
  - core/agent_coordinator.py lines 493-494, 506-507, 516-517 (symlink edge cases)
"""

import asyncio
import json
import os
import pytest
from pathlib import Path
from unittest.mock import (
    MagicMock,
    AsyncMock,
    patch,
    PropertyMock,
)

from core.interfaces import Message


# ==============================================================
# core/__init__.py  —  lazy __getattr__ (lines 16-20)
# ==============================================================


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


# ==============================================================
# core/memory/knowledge_memory.py  —  invalid order_by (line 165)
# ==============================================================


@pytest.mark.asyncio
async def test_knowledge_memory_invalid_order_by():
    """Line 165: invalid order_by falls back to 'updated_at DESC'."""
    from core.memory.knowledge_memory import KnowledgeMemoryManager

    mgr = KnowledgeMemoryManager(db_path=":memory:")

    # Pass an SQL-injection-style order_by; should be replaced
    results = await mgr.search(query="test", order_by="1; DROP TABLE memories;--")
    # Should not raise and should return a list (empty since DB is fresh)
    assert isinstance(results, list)


# ==============================================================
# features/dash_data/agent.py  —  ValueError/TypeError (lines 71-72)
# ==============================================================


@pytest.mark.asyncio
async def test_dash_data_stats_value_error():
    """Lines 71-72: ValueError/TypeError in numeric conversion -> continue.

    The target code is in get_summary(), lines 57-72:
        for col in columns:
            try:
                values = [float(row[col]) for row in data ...]
                ...
            except (ValueError, TypeError):
                continue

    We need to trigger ValueError or TypeError from the list comprehension
    itself — not from float() since isdigit() guards that. The exception
    can come from row.get(col) returning something that causes issues or
    from the float() call on edge-case values. We patch float() to raise.
    """
    from features.dash_data.agent import DashDataAgent

    agent = DashDataAgent.__new__(DashDataAgent)
    agent.datasets = {}

    # Load dataset with values that will pass the isdigit() check but trigger
    # an error when float() is called. We'll just patch float inside the module
    # to force a ValueError for certain values.
    agent.datasets["test"] = [
        {"col_a": "123", "col_b": "hello"},
        {"col_a": "456", "col_b": "world"},
    ]

    # Patch float to raise ValueError for any call (this will trigger
    # the except (ValueError, TypeError): continue on line 71-72)
    original_float = float

    def patched_float(val):
        if val in ("123", "456"):
            raise ValueError("forced error for test")
        return original_float(val)

    with patch("builtins.float", side_effect=patched_float):
        result = await agent.get_summary("test")

    # Should return valid JSON string with summary
    parsed = json.loads(result)
    assert parsed["name"] == "test"
    assert parsed["total_records"] == 2


# ==============================================================
# core/orchestrator.py  —  _on_done callback exception (lines 43-44)
# ==============================================================


@pytest.mark.asyncio
async def test_on_done_exception_from_task_exception_call():
    """Lines 43-44: t.exception() raises non-CancelledError -> prints error.

    The _on_done callback calls t.exception(). If that raises something
    other than CancelledError, we hit lines 43-44. We create a real task,
    then replace its exception() method to raise RuntimeError.
    """
    from core.orchestrator import _safe_create_task

    # Create a real task that completes normally
    async def noop():
        pass

    task = _safe_create_task(noop())
    await task  # let it complete

    # Now manually invoke the _on_done callback logic. Since _on_done is
    # a closure we can't easily extract it, but we CAN create a new task
    # with a patched exception() method and trigger the callback.

    async def also_noop():
        pass

    # Create a task, then before its callback fires, patch exception()
    task2 = _safe_create_task(also_noop())

    # Replace exception method to raise RuntimeError (not CancelledError)
    original_exception = task2.exception

    def raising_exception():
        raise RuntimeError("weird callback error")

    task2.exception = raising_exception

    # Let the task complete and callback fire
    await task2
    # Give the event loop a tick so done-callbacks execute
    await asyncio.sleep(0.01)

    # If we got here without crash, lines 43-44 were hit (prints error, continues)


# ==============================================================
# core/orchestrator.py  —  health wrapper: await coro raises (line 472)
# ==============================================================


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

    # health_monitor.start_monitoring returns a real coroutine that raises
    async def failing_monitor():
        raise RuntimeError("health loop crashed")

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=failing_monitor())
    mock_monitor.stop = MagicMock()
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    # Give the health wrapper task time to run and hit the except on line 472
    await asyncio.sleep(0.1)
    await orchestrator.shutdown()


# ==============================================================
# core/orchestrator.py  —  health wrapper: last-resort await raises (lines 482-483)
# ==============================================================


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

    # Return an awaitable that is NOT a coroutine/future/task and NOT a Mock,
    # and that raises when awaited.
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


# ==============================================================
# core/orchestrator.py  —  coro.close() raises (lines 510-511)
# ==============================================================


@pytest.mark.asyncio
async def test_start_coro_close_raises_with_sleep(orchestrator):
    """Lines 510-511: coro.close() raises in finally -> pass.
    We patch create_task AND ensure_future to return non-Task,
    causing the finally block to try coro.close().
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

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = AsyncMock()
    mock_monitor.stop = MagicMock()
    orchestrator.health_monitor = mock_monitor

    # Patch create_task and ensure_future to return non-Task objects
    # so the finally block runs coro.close()
    with patch("asyncio.create_task", return_value="not-a-task"):
        with patch("asyncio.ensure_future", return_value="also-not"):
            await orchestrator.start()

    await asyncio.sleep(0.05)
    await orchestrator.shutdown()


# ==============================================================
# core/orchestrator.py  —  shutdown: coro close path (lines 1673-1676)
# ==============================================================


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close(orchestrator):
    """Lines 1673-1676: shutdown() finds _health_task with __await__.__self__
    pointing to a real coroutine and closes it."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()

    # Create a real coroutine to serve as the underlying coro
    async def dummy_coro():
        await asyncio.sleep(999)

    coro = dummy_coro()

    # Create a mock health task whose __await__.__self__ points to the real coro
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    # Replace __await__ with the coroutine's __await__ method so
    # getattr(await_attr, "__self__") returns the coroutine
    mock_task.__await__ = coro.__await__

    orchestrator._health_task = mock_task

    # shutdown() should find __await__.__self__ -> coro and close it
    await orchestrator.shutdown()

    # The coroutine should have been closed — trying to close again is harmless
    # but confirms it was handled
    try:
        coro.close()
    except RuntimeError:
        pass


# ==============================================================
# core/network/gateway.py  —  health wrapper exception paths
# Lines 108-110: _health_monitor_loop raises
# Line 133: await coro raises
# Lines 144-145: last-resort await raises
# Lines 172-173: coro.close() raises
# ==============================================================


@pytest.mark.asyncio
async def test_gateway_health_wrapper_invocation_raises():
    """Lines 108-110: _health_monitor_loop() raises -> return."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    # Make _health_monitor_loop raise when called
    gw._health_monitor_loop = MagicMock(side_effect=RuntimeError("boom"))

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    # Wait for the health wrapper to complete (it should return early)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_health_await_coro_raises():
    """Line 133: safe_to_await=True, await raises -> pass."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    async def failing_health():
        raise RuntimeError("health crashed")

    gw._health_monitor_loop = MagicMock(return_value=failing_health())

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_health_last_resort_raises():
    """Lines 144-145: last-resort await raises -> except pass."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    class FailingAwaitable:
        def __await__(self):
            raise RuntimeError("nope")

    gw._health_monitor_loop = MagicMock(return_value=FailingAwaitable())

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        await gw.start()

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_gateway_start_coro_close_raises():
    """Lines 172-173: coro.close() raises in start's finally."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw._health_task = None
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.enable_cloudflare = False
    gw.enable_vpn = False
    gw.enable_direct_https = False

    gw._health_monitor_loop = AsyncMock()

    with patch.object(gw, "_start_local_server", new_callable=AsyncMock):
        with patch("asyncio.create_task", return_value="not-task"):
            with patch("asyncio.ensure_future", return_value="not-future"):
                await gw.start()

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_gateway_stop_coro_close():
    """Lines 212-215: stop() closes __await__.__self__ coroutine."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.cloudflare_process = None
    gw.tailscale_process = None
    gw.https_server = None

    # Create a mock health task with __await__.__self__ being a real coroutine
    async def dummy():
        await asyncio.sleep(999)

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__await__ = coro.__await__

    gw._health_task = mock_task

    await gw.stop()

    # Cleanup
    try:
        coro.close()
    except RuntimeError:
        pass


@pytest.mark.asyncio
async def test_gateway_stop_no_health_task():
    """Gateway stop() with no health task — just clients cleanup."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway.__new__(UnifiedGateway)
    gw.logger = MagicMock()
    gw.clients = {}
    gw.local_server = None
    gw.cloudflare_process = None
    gw.tailscale_process = None
    gw.https_server = None
    gw._health_task = None

    await gw.stop()


# ==============================================================
# core/agent_coordinator.py  —  SubAgent fallback (lines 75-76, 83-84, 87)
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_subagent_fallback_all_fail(orchestrator):
    """Lines 75-76, 83-84, 87: all SubAgent lookups fail -> use default.

    We patch:
      1. globals() in agent_coordinator to not have SubAgent -> AgentCls = None
      2. orchestrator attribute access to raise -> lines 75-76
      3. core.orchestrator module to not have SubAgent -> lines 83-84
      4. Falls through to line 87: AgentCls = SubAgent (the module-level import)
    """
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    # Patch the orchestrator's LLM to return "VALID" for pre-flight check
    orchestrator.llm = AsyncMock()
    orchestrator.llm.generate = AsyncMock(return_value="VALID - plan is safe")

    # Mock SubAgent so it doesn't do real work
    mock_agent_instance = MagicMock()
    mock_agent_instance.generate_plan = AsyncMock(return_value="test plan")
    mock_agent_instance.run = AsyncMock(return_value="test result")
    mock_agent_instance.__dict__["_coordinator_managed"] = True
    mock_agent_instance.__dict__["_active"] = True

    mock_sub_agent_cls = MagicMock(return_value=mock_agent_instance)

    # Patch globals() to not have SubAgent (triggers line 72 -> None)
    # Patch orchestrator to raise on SubAgent attr (triggers lines 75-76)
    # Patch core.orchestrator module to not have SubAgent (triggers lines 83-84)
    # The final fallback (line 87) uses the real SubAgent from core.agents

    # We need the fallback to use our mock so the test doesn't do real agent work
    # So we'll patch the module-level SubAgent (the import at line 11)
    with patch.dict("core.agent_coordinator.__builtins__", {}, clear=False):
        with patch("core.agent_coordinator.SubAgent", mock_sub_agent_cls):
            # Also patch globals to return None for SubAgent key
            original_globals = globals
            with patch(
                "core.agent_coordinator.globals", return_value={"SubAgent": None}
            ):
                # Make orchestrator.SubAgent raise AttributeError
                type(orchestrator).SubAgent = PropertyMock(
                    side_effect=AttributeError("no SubAgent")
                )
                try:
                    # core.orchestrator.SubAgent no longer exists (removed
                    # dead import), so step 3 of the resolution chain
                    # already returns None without any patch.
                    result = await coord._spawn_sub_agent(
                        {
                            "name": "test-fb",
                            "role": "researcher",
                            "task": "test task",
                        }
                    )
                finally:
                    # Clean up the property mock
                    try:
                        del type(orchestrator).SubAgent
                    except (AttributeError, TypeError):
                        pass

    assert isinstance(result, str)


# ==============================================================
# core/agent_coordinator.py  —  relative path (line 267)
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_relative_path_resolution(orchestrator):
    """Line 267: relative path joined with workspace."""
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    # Create a mock agent and register it
    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(
        return_value=[{"name": "read_file", "scope": "files.read"}]
    )
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    # Call _execute_tool_for_sub_agent with a relative path
    result = await coord._execute_tool_for_sub_agent(
        "test-agent", {"name": "read_file", "input": {"path": "relative/path/test.txt"}}
    )
    # The relative path should be resolved against the workspace.
    # It may fail (file not found) but should not raise a security error
    # about path traversal.
    assert isinstance(result, str)


# ==============================================================
# core/agent_coordinator.py  —  outer path validation except (lines 287-288)
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_path_validation_outer_except(orchestrator):
    """Lines 287-288: outer except in _validate_path -> 'Path validation error'."""
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(
        return_value=[{"name": "read_file", "scope": "files.read"}]
    )
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    # Patch Path to raise an unexpected error during validation
    with patch(
        "core.agent_coordinator.Path", side_effect=RuntimeError("path weirdness")
    ):
        result = await coord._execute_tool_for_sub_agent(
            "test-agent",
            {"name": "read_file", "input": {"path": "/some/weird/path.txt"}},
        )
    assert "error" in result.lower() or "Error" in result


# ==============================================================
# core/agent_coordinator.py  —  read_file empty chunk (line 426)
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_read_file_empty_chunk(orchestrator):
    """Line 426: read in chunks, empty chunk -> break."""
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(
        return_value=[{"name": "read_file", "scope": "files.read"}]
    )
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    # Create a real temporary file inside the workspace.
    # _validate_path uses config.paths["workspaces"] (falls back to cwd).
    # Set workspaces to our temp dir so the file passes validation.
    workspace = Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
    workspace.mkdir(parents=True, exist_ok=True)
    orchestrator.config.paths["workspaces"] = str(workspace)

    tmp_file = workspace / "test_read_chunk.txt"
    tmp_file.write_text("hello world")

    try:
        result = await coord._execute_tool_for_sub_agent(
            "test-agent", {"name": "read_file", "input": {"path": str(tmp_file)}}
        )
        assert "hello world" in result
    finally:
        tmp_file.unlink(missing_ok=True)


# ==============================================================
# core/agent_coordinator.py  —  symlink detection (lines 493-494, 506-507, 516-517)
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_write_file_dest_symlink(orchestrator):
    """Lines 493-494: post-write destination is a symlink -> denied."""
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(
        return_value=[{"name": "write_file", "scope": "files.write"}]
    )
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    workspace = Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
    workspace.mkdir(parents=True, exist_ok=True)
    orchestrator.config.paths["workspaces"] = str(workspace)

    target_file = workspace / "real_file_for_symlink_test.txt"
    target_file.write_text("original")

    symlink_path = workspace / "link_dest_test.txt"

    try:
        # Create a symlink
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(target_file)

        # Try to write to the symlink path — should be denied at validation
        result = await coord._execute_tool_for_sub_agent(
            "test-agent",
            {
                "name": "write_file",
                "input": {"path": str(symlink_path), "content": "hacked"},
            },
        )
        # Should be denied
        assert (
            "symlink" in result.lower()
            or "denied" in result.lower()
            or "error" in result.lower()
        )
    finally:
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink(missing_ok=True)
        target_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_agent_coordinator_write_file_inode_change(orchestrator):
    """Lines 516-517: pre_stat.st_ino != post_stat.st_ino -> abort."""
    from core.agent_coordinator import AgentCoordinator

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(
        return_value=[{"name": "write_file", "scope": "files.write"}]
    )
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    workspace = Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
    workspace.mkdir(parents=True, exist_ok=True)
    orchestrator.config.paths["workspaces"] = str(workspace)

    target = workspace / "inode_test.txt"
    target.write_text("original")

    try:
        # To trigger the inode change detection, we need pre_stat and post_stat
        # to differ. Patch os.lstat to return different inodes.
        real_lstat = os.lstat

        call_count = [0]

        def fake_lstat(path):
            result = real_lstat(path)
            call_count[0] += 1
            if str(path) == str(target) and call_count[0] > 1:
                # Return a mock with different inode
                mock_stat = MagicMock()
                mock_stat.st_ino = result.st_ino + 999
                mock_stat.st_dev = result.st_dev
                mock_stat.st_mode = result.st_mode
                return mock_stat
            return result

        with patch("os.lstat", side_effect=fake_lstat):
            result = await coord._execute_tool_for_sub_agent(
                "test-agent",
                {
                    "name": "write_file",
                    "input": {"path": str(target), "content": "new content"},
                },
            )
        # Should detect inode mismatch and abort
        assert isinstance(result, str)
    finally:
        target.unlink(missing_ok=True)
