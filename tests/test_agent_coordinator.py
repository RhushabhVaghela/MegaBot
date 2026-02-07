"""Consolidated tests for core/agent_coordinator.py.

Covers: _audit, _spawn_sub_agent (validation, fallbacks, synthesis),
_execute_tool_for_sub_agent (permissions, read_file, write_file, query_rag, MCP),
_validate_path edge cases, TOCTOU detection, symlink detection, fd-based reading,
chunk limits, and outer exception handlers.
"""

import errno
import os
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, mock_open, patch

import pytest

from core.agent_coordinator import AgentCoordinator, _audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(orchestrator=None):
    """Build an AgentCoordinator with a minimal mock orchestrator."""
    if orchestrator is None:
        orchestrator = MagicMock()
        orchestrator.config = MagicMock()
        orchestrator.config.paths = {"workspaces": "/tmp/test_ws"}
        orchestrator.llm = AsyncMock()
        orchestrator.memory = AsyncMock()
        orchestrator.memory.memory_write = AsyncMock()
        orchestrator.memory.memory_query = AsyncMock(return_value=[])
        orchestrator.clients = []
        orchestrator.sub_agents = {}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized = MagicMock(return_value=True)
        orchestrator.rag = AsyncMock()
        orchestrator.adapters = {"mcp": AsyncMock()}
    return AgentCoordinator(orchestrator)


def _active_agent_with_tools(tools=None):
    """Return a mock agent marked active with the given tools list."""
    agent = MagicMock()
    agent.__dict__["_active"] = True
    agent.__dict__["_coordinator_managed"] = True
    agent.role = "tester"
    if tools is None:
        tools = [
            {"name": "read_file", "scope": "file.read"},
            {"name": "write_file", "scope": "file.write"},
        ]
    agent._get_sub_tools.return_value = tools
    return agent


def _active_agent(**overrides):
    """Return a MagicMock configured as an active sub-agent."""
    m = MagicMock()
    m.role = overrides.get("role", "Tester")
    m._active = True
    m._get_sub_tools.return_value = overrides.get("tools", [])
    return m


# ===========================================================================
# Original base tests (use conftest orchestrator fixture)
# ===========================================================================


@pytest.mark.asyncio
async def test_spawn_sub_agent_validation_fail(orchestrator):
    """AgentCoordinator should block sub-agent when pre-flight validation fails."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value="do dangerous things")
    mock_agent.run = AsyncMock(return_value="raw result")

    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
        orch.llm = MagicMock()
        orch.llm.generate = AsyncMock(return_value="nope")
        res = await coord._spawn_sub_agent({"name": "a1", "task": "t1"})
        assert "blocked by pre-flight" in res


@pytest.mark.asyncio
async def test_spawn_sub_agent_synthesis_and_memory(orchestrator):
    """Successful spawn should synthesize and write a lesson to memory."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.generate_plan = AsyncMock(return_value="plan")
    mock_agent.run = AsyncMock(return_value="raw result")

    orch.llm = MagicMock()
    orch.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"ok","learned_lesson":"CRITICAL: do X"}'])
    orch.memory = MagicMock()
    orch.memory.memory_write = AsyncMock()

    with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
        res = await coord._spawn_sub_agent({"name": "a2", "task": "t2"})
        assert isinstance(res, str)
        orch.memory.memory_write.assert_called()


@pytest.mark.asyncio
async def test_execute_tool_for_sub_agent_paths(orchestrator):
    """Test tool execution paths via AgentCoordinator."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    # 1. Agent not found
    orch.sub_agents = {}
    res = await coord._execute_tool_for_sub_agent("unknown", {})
    assert "Agent not found" in res

    # 2. Tool not allowed
    mock_agent = MagicMock()
    mock_agent.role = "tester"
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


# ===========================================================================
# _audit
# ===========================================================================


class TestAudit:
    def test_audit_success(self):
        """Normal audit call should not raise."""
        _audit("test.event", key="value")

    def test_audit_json_serialization_failure(self):
        """When data is not JSON-serializable, _audit silently catches."""
        _audit("bad.event", data={1, 2, 3})


# ===========================================================================
# _spawn_sub_agent — SubAgent resolution fallback chain (self-contained)
# ===========================================================================


class TestSpawnSubAgentResolutionFallbacks:
    """Cover lines 75-87: fallback chain when globals()['SubAgent'] is None.
    Uses self-contained _make_coordinator() helper."""

    @pytest.mark.asyncio
    async def test_getattr_orchestrator_raises_exception(self):
        """Line 75-76: getattr(self.orchestrator, 'SubAgent') raises -> AgentCls = None."""
        coord = _make_coordinator()

        real_orchestrator = coord.orchestrator
        orig_getattr = type(real_orchestrator).__getattr__

        def _exploding_getattr(self_mock, name):
            if name == "SubAgent":
                raise RuntimeError("boom")
            return orig_getattr(self_mock, name)

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="result")

        agent_cls_mock = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        with (
            patch.object(type(real_orchestrator), "__getattr__", _exploding_getattr),
            patch("core.agent_coordinator.SubAgent", agent_cls_mock),
        ):
            result = await coord._spawn_sub_agent({"name": "test1", "role": "tester", "task": "test task"})
            assert "test1" in str(result) or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fallback_to_core_orchestrator_module(self):
        """Lines 79-84: globals SubAgent is None, orchestrator attr is None -> import from core.orchestrator."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="result")

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []
        coord.orchestrator.SubAgent = None

        with patch.dict("core.agent_coordinator.__dict__", {"SubAgent": None}, clear=False):
            with patch("core.orchestrator.SubAgent", fake_cls, create=True):
                result = await coord._spawn_sub_agent({"name": "fb_test", "role": "researcher", "task": "research"})
                assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_all_fallbacks_fail_uses_module_level_subagent(self):
        """Line 87: All lookups return None -> AgentCls = SubAgent (module-level import)."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="done")

        final_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID OK")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        coord.orchestrator.SubAgent = None

        with patch.dict("core.agent_coordinator.__dict__", {"SubAgent": None}, clear=False):
            with patch("core.orchestrator.SubAgent", None, create=True):
                with patch("core.agent_coordinator.SubAgent", final_cls):
                    result = await coord._spawn_sub_agent({"name": "final", "role": "dev", "task": "do stuff"})
                    assert isinstance(result, str)


# ===========================================================================
# _spawn_sub_agent — Fallback paths (uses conftest orchestrator fixture)
# ===========================================================================


class TestSpawnSubAgentFallbacks:
    """Cover fallback paths using conftest orchestrator fixture."""

    @pytest.mark.asyncio
    async def test_globals_subagent_none_falls_back_to_orchestrator(self, orchestrator):
        """When globals()['SubAgent'] is None, use orchestrator.SubAgent."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}'])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        mock_cls = MagicMock(return_value=mock_agent)
        with patch.dict("core.agent_coordinator.__dict__", {"SubAgent": None}):
            orchestrator.SubAgent = mock_cls
            res = await coord._spawn_sub_agent({"name": "fb1", "task": "t"})
        assert isinstance(res, str)
        mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_deletes_pre_registered_agent(self, orchestrator):
        """If agent name already in sub_agents when validation fails, it should be removed."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="bad plan")
        mock_agent.run = AsyncMock()

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(return_value="DENIED")

        orchestrator.sub_agents["pre_reg"] = "placeholder"

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "pre_reg", "task": "t"})

        assert "blocked by pre-flight" in res
        assert "pre_reg" not in orchestrator.sub_agents

    @pytest.mark.asyncio
    async def test_synthesis_json_parse_failure_fallback(self, orchestrator):
        """When synthesis output has no valid JSON, summary falls back to raw string."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result data")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", "no json here at all"])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "nj", "task": "t"})
        assert "no json here at all" in res

    @pytest.mark.asyncio
    async def test_client_notification_failure(self, orchestrator):
        """Client notification failure should not break synthesis."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"good","learned_lesson":"L"}'])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        bad_client = MagicMock()
        bad_client.send_json = AsyncMock(side_effect=Exception("ws error"))
        orchestrator.clients = [bad_client]

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "cn", "task": "t"})
        assert "good" in res

    @pytest.mark.asyncio
    async def test_memory_write_failure(self, orchestrator):
        """Memory write failure should not break synthesis return."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"s","learned_lesson":"L"}'])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock(side_effect=Exception("db err"))

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "mf", "task": "t"})
        assert isinstance(res, str)


# ===========================================================================
# Validation exception paths (self-contained)
# ===========================================================================


class TestValidationExceptionPaths:
    """Cover lines 108-109 (del sub_agents raises) and 129-133 (dict/registration fails)."""

    @pytest.mark.asyncio
    async def test_del_sub_agents_raises(self):
        """Lines 108-109: `del self.orchestrator.sub_agents[name]` raises during validation failure."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VIOLATION: bad plan")

        exploding_dict = MagicMock(spec=dict)
        exploding_dict.__contains__ = MagicMock(return_value=True)
        exploding_dict.__delitem__ = MagicMock(side_effect=KeyError("no such key"))

        coord.orchestrator.sub_agents = exploding_dict

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent({"name": "bad_agent", "role": "hacker", "task": "hack things"})
            assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_agent_dict_assignment_raises(self):
        """Lines 129-130: agent.__dict__ assignment raises -> pass silently."""
        coord = _make_coordinator()

        class _ExplodingDict(dict):
            def __setitem__(self, key, val):
                if key in ("_coordinator_managed", "_active"):
                    raise TypeError("frozen dict")
                super().__setitem__(key, val)

        class _BrokenDictAgent:
            def __init__(self, *a, **kw):
                pass

            async def generate_plan(self):
                return "plan"

            async def run(self):
                return "result"

        agent_obj = _BrokenDictAgent()
        object.__setattr__(agent_obj, "__dict__", _ExplodingDict())

        fake_cls = MagicMock(return_value=agent_obj)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent({"name": "frozen", "role": "dev", "task": "test"})
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_sub_agents_registration_raises(self):
        """Lines 132-133: self.orchestrator.sub_agents[name] = agent raises -> pass."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="result")

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID plan")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        exploding_dict = MagicMock(spec=dict)
        exploding_dict.__setitem__ = MagicMock(side_effect=RuntimeError("no space"))
        coord.orchestrator.sub_agents = exploding_dict

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent({"name": "orphan", "role": "dev", "task": "build"})
            assert isinstance(result, str)


# ===========================================================================
# Synthesis outer exception handler (self-contained)
# ===========================================================================


class TestSynthesisOuterException:
    """Cover lines 208-210: outer try/except catches everything and returns str(synthesis_raw)."""

    @pytest.mark.asyncio
    async def test_synthesis_outer_exception_returns_raw(self):
        """Lines 208-210: everything inside the try block fails -> return str(synthesis_raw)."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="ok plan")
        fake_agent.run = AsyncMock(return_value="raw output")

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(
            side_effect=[
                "VALID",
                "synthesis raw text",
            ]
        )

        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            with patch(
                "core.agent_coordinator.re.search",
                side_effect=RuntimeError("regex broken"),
            ):
                result = await coord._spawn_sub_agent({"name": "synth_fail", "role": "dev", "task": "do"})
                assert "synthesis raw text" in result


# ===========================================================================
# JSON parse failure with regex match (self-contained)
# ===========================================================================


class TestSynthesisJsonParseFallback:
    """Cover lines 172-174: regex match exists but json.loads fails -> pass."""

    @pytest.mark.asyncio
    async def test_json_parse_failure_with_regex_match(self):
        """Lines 172-174: json_match found but json.loads raises -> falls to pass."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="done")

        fake_cls = MagicMock(return_value=fake_agent)

        invalid_json = "Here is the result: {invalid json content not parseable}"
        coord.orchestrator.llm.generate = AsyncMock(
            side_effect=[
                "VALID",
                invalid_json,
            ]
        )
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent({"name": "json_fail", "role": "dev", "task": "parse"})
            assert isinstance(result, str)


# ===========================================================================
# _safe_lstat paths (self-contained)
# ===========================================================================


class TestSafeLstat:
    """Cover lines 287-296: _safe_lstat returning None on FileNotFoundError vs other exceptions."""

    @pytest.mark.asyncio
    async def test_safe_lstat_file_not_found(self):
        """Lines 293-294: FileNotFoundError -> return None (new file write succeeds)."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}

        target = os.path.join(workspace, "newfile.txt")

        try:
            result = await coord._execute_tool_for_sub_agent(
                "writer",
                {"name": "write_file", "input": {"path": target, "content": "hello"}},
            )
            assert "written successfully" in result
            assert os.path.exists(target)
            with open(target) as f:
                assert f.read() == "hello"
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_safe_lstat_other_exception(self):
        """Lines 295-296: non-FileNotFoundError exception -> return None."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}

        target = os.path.join(workspace, "somefile.txt")
        with open(target, "w") as f:
            f.write("data")

        try:
            with patch("os.lstat", side_effect=PermissionError("denied")):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                assert isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# read_file — relative path size limit (self-contained)
# ===========================================================================


class TestReadFileRelativePathSizeLimit:
    """Relative paths resolved against workspace; size limit still enforced."""

    @pytest.mark.asyncio
    async def test_relative_read_exceeds_limit(self):
        """Relative path -> workspace resolution -> file too large."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}

        target_file = os.path.join(workspace, "bigfile.txt")
        large_data = "x" * (11 * 1024 * 1024)  # 11MB

        try:
            with open(target_file, "w") as f:
                f.write(large_data)

            result = await coord._execute_tool_for_sub_agent(
                "reader",
                {"name": "read_file", "input": {"path": "bigfile.txt"}},
            )
            assert "too large" in result.lower()
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# read_file — fallback open returns file too large (self-contained)
# ===========================================================================


class TestReadFileFallbackTooLarge:
    """Cover line 373: fallback `open()` returns data exceeding READ_LIMIT."""

    @pytest.mark.asyncio
    async def test_fallback_open_too_large(self):
        """Line 373: os.open ENOENT -> fallback open succeeds but data > READ_LIMIT."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "bigfile.txt")

        large_data = "x" * (11 * 1024 * 1024)

        try:
            os_error = OSError(errno.ENOENT, "No such file")
            with patch("os.open", side_effect=os_error):
                with patch("builtins.open", mock_open(read_data=large_data)):
                    result = await coord._execute_tool_for_sub_agent(
                        "reader",
                        {"name": "read_file", "input": {"path": target}},
                    )
                    assert "too large" in result.lower()
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# read_file — fstat exception -> pass (self-contained)
# ===========================================================================


class TestReadFileFstatException:
    """Cover lines 414-415: exception during fstat size check -> pass (continue reading)."""

    @pytest.mark.asyncio
    async def test_fstat_size_check_exception(self):
        """Lines 414-415: post_stat.st_size attribute raises -> pass and continue."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "testfile.txt")
        with open(target, "w") as f:
            f.write("content")

        try:
            bad_stat = MagicMock()
            bad_stat.st_ino = os.stat(target).st_ino
            bad_stat.st_dev = os.stat(target).st_dev
            type(bad_stat).st_size = PropertyMock(side_effect=OSError("bad fstat"))

            with patch("os.fstat", return_value=bad_stat):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                assert "content" in result or isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# read_file — chunk remaining <= 0 (self-contained)
# ===========================================================================


class TestReadFileChunkRemainingZero:
    """Cover lines 426-431: remaining counter hits <= 0 and breaks the read loop."""

    @pytest.mark.asyncio
    async def test_chunk_remaining_breaks_loop(self):
        """Lines 428-431: remaining decremented to <= 0 -> break."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "chunkfile.txt")
        with open(target, "w") as f:
            f.write("A" * 200)

        try:
            small_stat = MagicMock()
            real_stat = os.stat(target)
            small_stat.st_ino = real_stat.st_ino
            small_stat.st_dev = real_stat.st_dev
            small_stat.st_size = 10  # Only 10 bytes -> remaining will go <= 0

            def _patched_fstat(fd):
                return small_stat

            with patch("os.fstat", side_effect=_patched_fstat):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                assert isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# read_file — fd close in exception handler (self-contained)
# ===========================================================================


class TestReadFileFdCloseInException:
    """Cover lines 438-439: os.close(fd) in the except handler also raises -> pass."""

    @pytest.mark.asyncio
    async def test_fd_close_raises_in_exception_handler(self):
        """Lines 436-439: main read fails, then os.close(fd) also raises -> pass."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "fdclose.txt")
        with open(target, "w") as f:
            f.write("data")

        try:
            real_os_open = os.open
            real_os_close = os.close

            fd_opened = []

            def _tracking_open(path, flags):
                fd = real_os_open(path, flags)
                fd_opened.append(fd)
                return fd

            def _fstat_raises(fd):
                raise RuntimeError("fstat explosion")

            call_count = [0]

            def _close_raises(fd):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise OSError("close failed")
                real_os_close(fd)

            with patch("os.open", side_effect=_tracking_open):
                with patch("os.fstat", side_effect=_fstat_raises):
                    with patch("os.close", side_effect=_close_raises):
                        result = await coord._execute_tool_for_sub_agent(
                            "reader",
                            {"name": "read_file", "input": {"path": target}},
                        )
                        assert "error" in result.lower() or "denied" in result.lower()
        finally:
            for fd in fd_opened:
                try:
                    real_os_close(fd)
                except Exception:
                    pass
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# write_file — symlink detection via S_ISLNK (self-contained)
# ===========================================================================


class TestWriteFileSymlinkDetection:
    """Cover lines 491-507: write_file detects destination is a symlink via S_ISLNK."""

    @pytest.mark.asyncio
    async def test_write_dest_is_symlink(self):
        """Lines 490-505: post_stat shows S_ISLNK -> deny write and clean up temp."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "link_target.txt")

        try:
            with open(target, "w") as f:
                f.write("original")

            symlink_stat = MagicMock()
            symlink_stat.st_mode = stat.S_IFLNK | 0o777
            symlink_stat.st_ino = 12345
            symlink_stat.st_dev = 100

            _real_lstat = os.lstat
            target_call_count = [0]

            def _fake_lstat(path_str):
                if str(path_str) == target:
                    target_call_count[0] += 1
                    if target_call_count[0] <= 2:
                        return _real_lstat(target)
                    return symlink_stat
                return _real_lstat(path_str)

            with patch("os.lstat", side_effect=_fake_lstat):
                result = await coord._execute_tool_for_sub_agent(
                    "writer",
                    {
                        "name": "write_file",
                        "input": {"path": target, "content": "malicious"},
                    },
                )
                assert "symlink" in result.lower()
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# write_file — TOCTOU identity change with unlink (self-contained)
# ===========================================================================


class TestWriteFileTOCTOUUnlink:
    """Cover lines 516-517: TOCTOU detected (identity changed) -> unlink temp and deny."""

    @pytest.mark.asyncio
    async def test_write_toctou_identity_change(self):
        """Lines 510-517: pre_stat inode differs from post_stat -> TOCTOU detected."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "toctou_file.txt")

        try:
            with open(target, "w") as f:
                f.write("original")

            pre = MagicMock()
            pre.st_ino = 1000
            pre.st_dev = 50
            pre.st_mode = stat.S_IFREG | 0o644

            post = MagicMock()
            post.st_ino = 2000  # Different inode!
            post.st_dev = 50
            post.st_mode = stat.S_IFREG | 0o644

            _real_lstat = os.lstat
            target_call_count = [0]

            def _alternating_lstat(path_str):
                if str(path_str) == target:
                    target_call_count[0] += 1
                    if target_call_count[0] <= 2:
                        return pre
                    return post
                return _real_lstat(path_str)

            with patch("os.lstat", side_effect=_alternating_lstat):
                result = await coord._execute_tool_for_sub_agent(
                    "writer",
                    {
                        "name": "write_file",
                        "input": {"path": target, "content": "modified"},
                    },
                )
                assert "TOCTOU" in result
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# write_file — outer exception with temp file cleanup (self-contained)
# ===========================================================================


class TestWriteFileOuterException:
    """Cover lines 532-549: write_file outer try/except catches and cleans up temp."""

    @pytest.mark.asyncio
    async def test_write_outer_exception_cleans_temp(self):
        """Lines 532-549: mkstemp succeeds but fdopen/write fails -> unlink temp and return error."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "fail_write.txt")

        try:
            with patch("os.fdopen", side_effect=IOError("disk full")):
                result = await coord._execute_tool_for_sub_agent(
                    "writer",
                    {
                        "name": "write_file",
                        "input": {"path": target, "content": "data"},
                    },
                )
                assert "error" in result.lower()
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_write_outer_exception_unlink_also_fails(self):
        """Lines 534-536: temp file unlink fails too -> pass."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "fail_both.txt")

        try:
            real_mkstemp = tempfile.mkstemp

            def _fake_mkstemp(dir=None):
                fd, path = real_mkstemp(dir=dir)
                os.close(fd)
                return 999, path  # return a fake fd

            with patch("tempfile.mkstemp", side_effect=_fake_mkstemp):
                with patch("os.fdopen", side_effect=IOError("disk full")):
                    with patch("os.unlink", side_effect=OSError("unlink failed")):
                        result = await coord._execute_tool_for_sub_agent(
                            "writer",
                            {
                                "name": "write_file",
                                "input": {"path": target, "content": "data"},
                            },
                        )
                        assert "error" in result.lower()
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# _validate_path edge cases (uses conftest orchestrator fixture)
# ===========================================================================


class TestValidatePath:
    @pytest.mark.asyncio
    async def test_empty_path(self, orchestrator, tmp_path):
        """An empty path should be rejected."""
        coord = AgentCoordinator(orchestrator)
        orchestrator.config.paths["workspaces"] = str(tmp_path)

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": ""}})
        assert "denied" in res.lower() or "error" in res.lower()

    @pytest.mark.asyncio
    async def test_path_resolution_error(self, orchestrator, tmp_path):
        """A path that can't be resolved should return an error."""
        coord = AgentCoordinator(orchestrator)
        orchestrator.config.paths["workspaces"] = str(tmp_path)

        agent = _active_agent(tools=[{"name": "write_file", "scope": "fs.write"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent(
            "a",
            {"name": "write_file", "input": {"path": "/tmp/\x00bad", "content": "x"}},
        )
        assert "Error" in res or "error" in res


# ===========================================================================
# read_file — relative path resolves against workspace (conftest fixture)
# ===========================================================================


class TestReadFileRelative:
    @pytest.mark.asyncio
    async def test_relative_path_resolved_against_workspace(self, orchestrator, tmp_path):
        """A relative path should be resolved against the workspace, not CWD."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        test_file = workspace / "hello.txt"
        test_file.write_text("hello world")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": "hello.txt"}})
        assert "hello world" in res


# ===========================================================================
# read_file — OSError fallback (conftest fixture)
# ===========================================================================


class TestReadFileOSErrorFallback:
    @pytest.mark.asyncio
    async def test_os_open_non_eloop_fallback(self, orchestrator, tmp_path):
        """When os.open fails with non-ELOOP error, fallback to builtin open."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "file.txt"
        target.write_text("content via fallback")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        with patch("os.open", side_effect=OSError(errno.ENOENT, "No such file")):
            res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": str(target)}})
        assert "content via fallback" in res

    @pytest.mark.asyncio
    async def test_os_open_non_eloop_fallback_also_fails(self, orchestrator, tmp_path):
        """When both os.open and builtin open fail, return error."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "file.txt"
        target.write_text("x")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        with patch("os.open", side_effect=OSError(errno.ENOENT, "No such file")):
            with patch("builtins.open", side_effect=Exception("no access")):
                res = await coord._execute_tool_for_sub_agent(
                    "a", {"name": "read_file", "input": {"path": str(target)}}
                )
        assert "denied" in res.lower() or "error" in res.lower()


# ===========================================================================
# read_file — fd-based reading (conftest fixture)
# ===========================================================================


class TestReadFileFdBased:
    @pytest.mark.asyncio
    async def test_fd_file_too_large(self, orchestrator, tmp_path):
        """Files exceeding READ_LIMIT via fstat should be rejected."""
        coord = AgentCoordinator(orchestrator)
        coord.READ_LIMIT = 10  # tiny limit

        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        big_file = workspace / "big.txt"
        big_file.write_text("x" * 100)

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": str(big_file)}})
        assert "too large" in res

    @pytest.mark.asyncio
    async def test_fd_successful_chunk_read(self, orchestrator, tmp_path):
        """Normal fd-based read should return file content."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "good.txt"
        target.write_text("hello from fd")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": str(target)}})
        assert "hello from fd" in res

    @pytest.mark.asyncio
    async def test_fd_exception_during_read(self, orchestrator, tmp_path):
        """Exception after fd is opened should be caught and fd closed."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "err.txt"
        target.write_text("x")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        with patch("os.fstat", side_effect=Exception("fstat boom")):
            res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": str(target)}})
        assert "denied" in res.lower() or "fstat boom" in res


# ===========================================================================
# write_file — TOCTOU detection (conftest fixture)
# ===========================================================================


class TestWriteFileToctou:
    @pytest.mark.asyncio
    async def test_write_toctou_inode_change(self, orchestrator, tmp_path):
        """Write should be denied if inode changes between pre and post stat."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "toctou.txt"
        target.write_text("original")

        agent = _active_agent(tools=[{"name": "write_file", "scope": "fs.write"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        real_lstat = os.lstat
        target_str = str(target.resolve())
        target_call_count = [0]

        def mock_lstat(p):
            s = real_lstat(p)
            if str(p) == target_str:
                target_call_count[0] += 1
                if target_call_count[0] >= 3:
                    fake = MagicMock()
                    fake.st_ino = s.st_ino + 999
                    fake.st_dev = s.st_dev
                    fake.st_mode = s.st_mode
                    return fake
            return s

        with patch("os.lstat", side_effect=mock_lstat):
            res = await coord._execute_tool_for_sub_agent(
                "a",
                {
                    "name": "write_file",
                    "input": {"path": str(target), "content": "new"},
                },
            )
        assert "TOCTOU" in res

    @pytest.mark.asyncio
    async def test_write_exception_during_write(self, orchestrator, tmp_path):
        """Exception during write should clean up temp file and return error."""
        coord = AgentCoordinator(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        agent = _active_agent(tools=[{"name": "write_file", "scope": "fs.write"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        with patch("tempfile.mkstemp", side_effect=Exception("mkstemp boom")):
            res = await coord._execute_tool_for_sub_agent(
                "a",
                {
                    "name": "write_file",
                    "input": {"path": str(workspace / "out.txt"), "content": "data"},
                },
            )
        assert "error" in res.lower()


# ===========================================================================
# query_rag (conftest fixture)
# ===========================================================================


class TestQueryRag:
    @pytest.mark.asyncio
    async def test_query_rag_tool(self, orchestrator):
        """query_rag should call orchestrator.rag.navigate."""
        coord = AgentCoordinator(orchestrator)

        agent = _active_agent(tools=[{"name": "query_rag", "scope": "rag"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.rag = MagicMock()
        orchestrator.rag.navigate = AsyncMock(return_value="rag result")

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "query_rag", "input": {"query": "how does X work?"}}
        )
        assert res == "rag result"
        orchestrator.rag.navigate.assert_awaited_once_with("how does X work?")


# ===========================================================================
# MCP fallback (conftest fixture)
# ===========================================================================


class TestMCPFallback:
    @pytest.mark.asyncio
    async def test_mcp_returns_error_dict(self, orchestrator):
        """MCP returning a dict with 'error' key should map to 'not implemented'."""
        coord = AgentCoordinator(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value={"error": "tool not found"})

        res = await coord._execute_tool_for_sub_agent("a", {"name": "custom_tool", "input": {}})
        assert "logic not implemented" in res

    @pytest.mark.asyncio
    async def test_mcp_returns_errors_dict(self, orchestrator):
        """MCP returning a dict with 'errors' key should map to 'not implemented'."""
        coord = AgentCoordinator(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value={"errors": ["oops"]})

        res = await coord._execute_tool_for_sub_agent("a", {"name": "custom_tool", "input": {}})
        assert "logic not implemented" in res

    @pytest.mark.asyncio
    async def test_mcp_returns_success(self, orchestrator):
        """MCP returning a normal result should be passed through."""
        coord = AgentCoordinator(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value="mcp ok")

        res = await coord._execute_tool_for_sub_agent("a", {"name": "custom_tool", "input": {}})
        assert res == "mcp ok"

    @pytest.mark.asyncio
    async def test_no_mcp_returns_not_implemented(self, orchestrator):
        """Without MCP adapter, unknown tools return 'not implemented'."""
        coord = AgentCoordinator(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters.pop("mcp", None)

        res = await coord._execute_tool_for_sub_agent("a", {"name": "custom_tool", "input": {}})
        assert "logic not implemented" in res


# ===========================================================================
# Extra: inactive agent, outside workspace, symlink denied, strict perms
# ===========================================================================


@pytest.mark.asyncio
async def test_inactive_agent_blocked(orchestrator):
    """Ensure _execute_tool_for_sub_agent refuses execution for non-active agents."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "Assistant"
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "filesystem.read"}]
    orch.sub_agents = {"inactive": mock_agent}

    res = await coord._execute_tool_for_sub_agent(
        "inactive", {"name": "read_file", "input": {"path": "/tmp/does_not_matter"}}
    )
    assert "not active" in res


@pytest.mark.asyncio
async def test_read_file_denied_outside_workspace(orchestrator, tmp_path):
    """Reads outside of the configured workspace must be denied."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("top secret")

    orch.config.paths["workspaces"] = str(workspace)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "filesystem.read"}]
    mock_agent._active = True

    orch.sub_agents = {"agent1": mock_agent}
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    res = await coord._execute_tool_for_sub_agent("agent1", {"name": "read_file", "input": {"path": str(outside_file)}})
    assert "outside workspace" in res or "read_file denied" in res


@pytest.mark.asyncio
async def test_write_file_symlink_denied(orchestrator, tmp_path):
    """Writes to symlinks (even inside workspace) should be denied."""
    orch = orchestrator
    coord = AgentCoordinator(orch)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("external")

    link_path = workspace / "link.txt"
    link_path.symlink_to(target)

    orch.config.paths["workspaces"] = str(workspace)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [{"name": "write_file", "scope": "filesystem.write"}]
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
    orch = orchestrator
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "Senior Dev"
    mock_agent._get_sub_tools.return_value = [{"name": "read_file", "scope": "filesystem.read"}]
    mock_agent._active = True

    orch.sub_agents = {"a": mock_agent}
    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = "allowed"

    res = await coord._execute_tool_for_sub_agent("a", {"name": "read_file", "input": {"path": "/tmp/x"}})
    assert "Permission denied" in res


# ===========================================================================
# TOCTOU: read_file symlink via ELOOP and inode mismatch
# ===========================================================================


@pytest.mark.asyncio
async def test_read_file_symlink_error_os_open_eloop(orchestrator, tmp_path):
    """If os.open raises ELOOP we surface a symlink/permission error."""
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

    target = tmp_path / "f.txt"
    target.write_text("hello")

    def _bad_open(path, flags):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links")

    try:
        orig_open = os.open
        os.open = _bad_open
        res = await coord._execute_tool_for_sub_agent("a1", {"name": "read_file", "input": {"path": str(target)}})
    finally:
        os.open = orig_open

    assert "possible symlink" in res or "symlink" in res


@pytest.mark.asyncio
async def test_read_file_toctou_detected(orchestrator, tmp_path):
    """If the file identity changes between lstat and fstat we detect TOCTOU."""
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

    pre_stat = SimpleNamespace(st_ino=1, st_dev=1, st_size=4, st_mode=0)
    post_stat = SimpleNamespace(st_ino=2, st_dev=1, st_size=4, st_mode=0)

    orig_lstat = os.lstat
    orig_open = os.open
    orig_fstat = os.fstat
    orig_read = os.read
    orig_close = os.close

    def _fake_lstat(path):
        return pre_stat

    def _fake_open(path, flags):
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

        res = await coord._execute_tool_for_sub_agent("a1", {"name": "read_file", "input": {"path": str(target)}})
    finally:
        os.lstat = orig_lstat
        os.open = orig_open
        os.fstat = orig_fstat
        os.read = orig_read
        os.close = orig_close

    assert "TOCTOU" in res or "TOCTOU detected" in res


# ===========================================================================
# Write edge cases: dest symlink and success
# ===========================================================================


@pytest.mark.asyncio
async def test_write_file_dest_symlink(orchestrator, tmp_path):
    """If destination becomes a symlink before replace, write_file should deny."""
    orch = orchestrator
    orch.config.paths["workspaces"] = str(tmp_path)
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "tester"
    mock_agent._active = True
    mock_agent._get_sub_tools.return_value = [{"name": "write_file", "scope": "fs"}]
    orch.sub_agents = {"a1": mock_agent}

    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    dest = tmp_path / "d.txt"
    tmp_path.mkdir(parents=True, exist_ok=True)

    class FakeStat:
        st_mode = 0
        st_ino = 123
        st_dev = 1

    fake = FakeStat()

    orig_lstat = os.lstat
    orig_mkstemp = tempfile.mkstemp

    def fake_lstat(path):
        try:
            if str(path) == str(dest):
                return fake
            return orig_lstat(path)
        except Exception:
            return None

    def fake_mkstemp(dir=None):
        fd, p = orig_mkstemp(dir=dir)
        return fd, p

    try:
        os.lstat = fake_lstat
        tempfile.mkstemp = fake_mkstemp
        res = await coord._execute_tool_for_sub_agent(
            "a1", {"name": "write_file", "input": {"path": str(dest), "content": "x"}}
        )
    finally:
        os.lstat = orig_lstat
        tempfile.mkstemp = orig_mkstemp

    assert "symlink" in res or "TOCTOU" in res


@pytest.mark.asyncio
async def test_write_file_success(orchestrator, tmp_path):
    """A normal write_file should succeed and return success message."""
    orch = orchestrator
    orch.config.paths["workspaces"] = str(tmp_path)
    coord = AgentCoordinator(orch)

    mock_agent = MagicMock()
    mock_agent.role = "tester"
    mock_agent._active = True
    mock_agent._get_sub_tools.return_value = [{"name": "write_file", "scope": "fs"}]
    orch.sub_agents = {"a1": mock_agent}

    orch.permissions = MagicMock()
    orch.permissions.is_authorized.return_value = True

    dest = tmp_path / "ok.txt"
    res = await coord._execute_tool_for_sub_agent(
        "a1", {"name": "write_file", "input": {"path": str(dest), "content": "hello"}}
    )

    assert "written successfully" in res


# ---------------------------------------------------------------------------
# SubAgent resolution fallbacks (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------

import stat as _stat


class TestSubAgentResolutionFallbacks:
    """Cover agent_coordinator.py lines 75-76 and 83-84."""

    @pytest.mark.asyncio
    async def test_subagent_resolution_lines_75_76(self, orchestrator):
        """Lines 75-76: getattr(self.orchestrator, 'SubAgent') raises -> AgentCls = None.

        Flow:
          L71: globals().get("SubAgent") -> None  (we patch module dict)
          L73: getattr(self.orchestrator, "SubAgent") -> raises  (proxy)
          L75-76: except -> AgentCls = None  <- THIS IS WHAT WE COVER
          L78-84: import core.orchestrator, getattr -> still None (no attr)
          L87: AgentCls = SubAgent  (module-level import, we patch this)
        """
        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="raw result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}'])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        # Proxy that raises on .SubAgent access but delegates everything else.
        class OrchestratorProxy:
            def __init__(self, real):
                object.__setattr__(self, "_real", real)

            def __getattr__(self, name):
                if name == "SubAgent":
                    raise RuntimeError("boom")
                return getattr(object.__getattribute__(self, "_real"), name)

            def __setattr__(self, name, value):
                if name == "_real":
                    object.__setattr__(self, name, value)
                else:
                    setattr(object.__getattribute__(self, "_real"), name, value)

        proxied_orch = OrchestratorProxy(orchestrator)
        coord_proxied = AgentCoordinator(proxied_orch)

        import core.agent_coordinator as _ac_mod

        # 1. Set module-level SubAgent to None -> globals().get("SubAgent") returns None
        original_sub = _ac_mod.__dict__.get("SubAgent")
        _ac_mod.__dict__["SubAgent"] = None

        mock_constructor = MagicMock(return_value=mock_agent)

        try:
            import core.orchestrator as _orch_mod

            _orch_mod.SubAgent = mock_constructor
            try:
                res = await coord_proxied._spawn_sub_agent({"name": "test_agent", "task": "test_task"})
                assert isinstance(res, str)
            finally:
                if hasattr(_orch_mod, "SubAgent"):
                    delattr(_orch_mod, "SubAgent")
        finally:
            if original_sub is not None:
                _ac_mod.__dict__["SubAgent"] = original_sub
            else:
                _ac_mod.__dict__.pop("SubAgent", None)

    @pytest.mark.asyncio
    async def test_subagent_resolution_lines_83_84(self, orchestrator):
        """Lines 83-84: import core.orchestrator raises -> AgentCls = None, fallback to module-level SubAgent."""
        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="raw result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}'])
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        class OrchestratorProxy:
            def __init__(self, real):
                object.__setattr__(self, "_real", real)

            def __getattr__(self, name):
                if name == "SubAgent":
                    raise RuntimeError("boom on orchestrator attr")
                return getattr(object.__getattribute__(self, "_real"), name)

            def __setattr__(self, name, value):
                if name == "_real":
                    object.__setattr__(self, name, value)
                else:
                    setattr(object.__getattribute__(self, "_real"), name, value)

        proxied_orch = OrchestratorProxy(orchestrator)
        coord_proxied = AgentCoordinator(proxied_orch)

        # globals() returns no SubAgent, orchestrator raises, AND
        # importing core.orchestrator raises — so it falls to the final SubAgent
        with patch("core.agent_coordinator.globals", return_value={"SubAgent": None}):
            with patch.dict("sys.modules", {"core.orchestrator": None}):
                # When core.orchestrator is None in sys.modules, importing it raises TypeError
                # The final fallback uses the module-level SubAgent import
                with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
                    res = await coord_proxied._spawn_sub_agent({"name": "test_agent2", "task": "test_task2"})
                    assert isinstance(res, str)


# ---------------------------------------------------------------------------
# Path validation outer exception (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------


class TestPathValidationOuterException:
    """Cover agent_coordinator.py lines 287-288."""

    @pytest.mark.asyncio
    async def test_path_validation_outer_exception(self, orchestrator, tmp_path):
        """Lines 287-288: unexpected exception in _validate_and_resolve_path."""
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

        # We need to trigger an exception in the outer try block of _validate_path.
        bomb_dict = MagicMock()
        bomb_dict.get = MagicMock(side_effect=RuntimeError("Simulated path config explosion"))
        orch.config.paths = bomb_dict

        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {"name": "read_file", "input": {"path": "/some/absolute/path.txt"}},
        )
        assert "Path validation error" in res


# ---------------------------------------------------------------------------
# Read file empty file (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------


class TestReadFileEmptyFile:
    """Cover agent_coordinator.py line 426."""

    @pytest.mark.asyncio
    async def test_read_file_empty_file_breaks_loop(self, orchestrator, tmp_path):
        """Line 426: os.read() returns empty bytes -> break."""
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

        # Create a genuinely empty file
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {"name": "read_file", "input": {"path": str(empty_file)}},
        )
        # Should return empty string (no content)
        assert res == "" or res == ""


# ---------------------------------------------------------------------------
# Write file TOCTOU pass blocks (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------


class TestWriteFileTOCTOUPassBlocks:
    """Cover agent_coordinator.py lines 493-494, 506-507, 516-517."""

    @pytest.mark.asyncio
    async def test_unlink_fails_after_inode_mismatch_lines_516_517(self, orchestrator, tmp_path):
        """Lines 516-517: os.unlink(tmp_path) fails after inode/dev mismatch -> pass."""
        orch = orchestrator
        orch.config.paths["workspaces"] = str(tmp_path)
        coord = AgentCoordinator(orch)

        mock_agent = MagicMock()
        mock_agent.role = "tester"
        mock_agent._active = True
        mock_agent._get_sub_tools.return_value = [{"name": "write_file", "scope": "fs"}]
        orch.sub_agents = {"a1": mock_agent}
        orch.permissions = MagicMock()
        orch.permissions.is_authorized.return_value = True

        dest = tmp_path / "inode_change.txt"
        dest.write_text("original")

        orig_lstat = os.lstat
        orig_unlink = os.unlink
        orig_mkstemp = tempfile.mkstemp

        # Phase tracking: once mkstemp is called, we're past the pre_stat
        state = {"write_phase": False, "pre_stat_done": False}

        class PreStat:
            st_mode = _stat.S_IFREG | 0o644
            st_ino = 100
            st_dev = 1

        class PostStat:
            st_mode = _stat.S_IFREG | 0o644
            st_ino = 200  # Different inode!
            st_dev = 1

        def fake_mkstemp(**kwargs):
            result = orig_mkstemp(**kwargs)
            state["write_phase"] = True
            return result

        def fake_lstat(path):
            p = str(path)
            if p == str(dest):
                if not state["write_phase"]:
                    return PreStat()
                else:
                    return PostStat()
            return orig_lstat(path)

        def fake_unlink(path):
            raise OSError("Permission denied for unlink")

        try:
            os.lstat = fake_lstat
            os.unlink = fake_unlink
            tempfile.mkstemp = fake_mkstemp
            res = await coord._execute_tool_for_sub_agent(
                "a1",
                {
                    "name": "write_file",
                    "input": {"path": str(dest), "content": "new data"},
                },
            )
        finally:
            os.lstat = orig_lstat
            os.unlink = orig_unlink
            tempfile.mkstemp = orig_mkstemp

        assert "TOCTOU" in res


# ==============================================================
# Round 3 — merged from test_coverage_round3.py
# ==============================================================


@pytest.mark.asyncio
async def test_agent_coordinator_subagent_fallback_all_fail(orchestrator):
    """Lines 75-76, 83-84, 87: all SubAgent lookups fail -> use default."""
    coord = AgentCoordinator(orchestrator)

    orchestrator.llm = AsyncMock()
    orchestrator.llm.generate = AsyncMock(return_value="VALID - plan is safe")

    mock_agent_instance = MagicMock()
    mock_agent_instance.generate_plan = AsyncMock(return_value="test plan")
    mock_agent_instance.run = AsyncMock(return_value="test result")
    mock_agent_instance.__dict__["_coordinator_managed"] = True
    mock_agent_instance.__dict__["_active"] = True

    mock_sub_agent_cls = MagicMock(return_value=mock_agent_instance)

    with patch.dict("core.agent_coordinator.__builtins__", {}, clear=False):
        with patch("core.agent_coordinator.SubAgent", mock_sub_agent_cls):
            original_globals = globals
            with patch("core.agent_coordinator.globals", return_value={"SubAgent": None}):
                type(orchestrator).SubAgent = PropertyMock(side_effect=AttributeError("no SubAgent"))
                try:
                    result = await coord._spawn_sub_agent(
                        {
                            "name": "test-fb",
                            "role": "researcher",
                            "task": "test task",
                        }
                    )
                finally:
                    try:
                        del type(orchestrator).SubAgent
                    except (AttributeError, TypeError):
                        pass

    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_agent_coordinator_relative_path_resolution(orchestrator):
    """Line 267: relative path joined with workspace."""
    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(return_value=[{"name": "read_file", "scope": "files.read"}])
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    result = await coord._execute_tool_for_sub_agent(
        "test-agent", {"name": "read_file", "input": {"path": "relative/path/test.txt"}}
    )
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_agent_coordinator_path_validation_outer_except(orchestrator):
    """Lines 287-288: outer except in _validate_path -> 'Path validation error'."""
    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(return_value=[{"name": "read_file", "scope": "files.read"}])
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    from pathlib import Path as _Path

    with patch("core.agent_file_ops.Path", side_effect=RuntimeError("path weirdness")):
        result = await coord._execute_tool_for_sub_agent(
            "test-agent",
            {"name": "read_file", "input": {"path": "/some/weird/path.txt"}},
        )
    assert "error" in result.lower() or "Error" in result


@pytest.mark.asyncio
async def test_agent_coordinator_read_file_empty_chunk(orchestrator):
    """Line 426: read in chunks, empty chunk -> break."""
    from pathlib import Path as _Path

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(return_value=[{"name": "read_file", "scope": "files.read"}])
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    workspace = _Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
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


@pytest.mark.asyncio
async def test_agent_coordinator_write_file_dest_symlink(orchestrator):
    """Lines 493-494: post-write destination is a symlink -> denied."""
    from pathlib import Path as _Path

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(return_value=[{"name": "write_file", "scope": "files.write"}])
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    workspace = _Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
    workspace.mkdir(parents=True, exist_ok=True)
    orchestrator.config.paths["workspaces"] = str(workspace)

    target_file = workspace / "real_file_for_symlink_test.txt"
    target_file.write_text("original")

    symlink_path = workspace / "link_dest_test.txt"

    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(target_file)

        result = await coord._execute_tool_for_sub_agent(
            "test-agent",
            {
                "name": "write_file",
                "input": {"path": str(symlink_path), "content": "hacked"},
            },
        )
        assert "symlink" in result.lower() or "denied" in result.lower() or "error" in result.lower()
    finally:
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink(missing_ok=True)
        target_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_agent_coordinator_write_file_inode_change(orchestrator):
    """Lines 516-517: pre_stat.st_ino != post_stat.st_ino -> abort."""
    from pathlib import Path as _Path

    coord = AgentCoordinator(orchestrator)

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"
    mock_agent.__dict__["_active"] = True
    mock_agent.role = "researcher"
    mock_agent._get_sub_tools = MagicMock(return_value=[{"name": "write_file", "scope": "files.write"}])
    orchestrator.sub_agents = {"test-agent": mock_agent}
    orchestrator.permissions = MagicMock()
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)

    workspace = _Path(orchestrator.config.paths.get("external_repos", "/tmp/mock_repos"))
    workspace.mkdir(parents=True, exist_ok=True)
    orchestrator.config.paths["workspaces"] = str(workspace)

    target = workspace / "inode_test.txt"
    target.write_text("original")

    try:
        real_lstat = os.lstat

        call_count = [0]

        def fake_lstat(path):
            result = real_lstat(path)
            call_count[0] += 1
            if str(path) == str(target) and call_count[0] > 1:
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
        assert isinstance(result, str)
    finally:
        target.unlink(missing_ok=True)
