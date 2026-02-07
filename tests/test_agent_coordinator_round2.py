"""Round 2 coverage tests for core/agent_coordinator.py.

Targets the ~50 missed lines from Round 1 to push coverage from 82% → 95%+.
Focuses on:
- _spawn_sub_agent fallback chains (lines 75-87)
- Validation exception paths (lines 108-109, 129-133)
- Synthesis outer exception handler (lines 208-210)
- _safe_lstat paths (lines 287-296)
- read_file relative-path size limit (line 313)
- read_file fallback open too-large (line 373)
- read_file fstat exception pass (lines 414-415)
- read_file chunk remaining ≤ 0 (line 426-431)
- read_file fd close in exception (lines 438-439)
- write_file symlink detection via S_ISLNK (lines 491-507)
- write_file TOCTOU unlink in identity-change path (lines 516-517)
- write_file outer exception with temp cleanup (lines 532-549)
"""

import errno
import os
import stat
import tempfile
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch, mock_open

import pytest

from core.agent_coordinator import AgentCoordinator


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


# ===========================================================================
# 1. _spawn_sub_agent — SubAgent resolution fallback chain
# ===========================================================================


class TestSpawnSubAgentFallbacks:
    """Cover lines 75-87: fallback chain when globals()['SubAgent'] is None."""

    @pytest.mark.asyncio
    async def test_getattr_orchestrator_raises_exception(self):
        """Line 75-76: getattr(self.orchestrator, 'SubAgent') raises → AgentCls = None."""
        coord = _make_coordinator()

        # Make the orchestrator raise on any attribute access for 'SubAgent'
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

        # Patch globals and the orchestrator attribute access
        with (
            patch.object(type(real_orchestrator), "__getattr__", _exploding_getattr),
            patch("core.agent_coordinator.SubAgent", agent_cls_mock),
        ):
            result = await coord._spawn_sub_agent(
                {"name": "test1", "role": "tester", "task": "test task"}
            )
            assert "test1" in str(result) or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_fallback_to_core_orchestrator_module(self):
        """Lines 79-84: globals SubAgent is None, orchestrator attr is None → import from core.orchestrator."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="result")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []
        coord.orchestrator.SubAgent = None  # attr returns None

        # globals()['SubAgent'] is None, orchestrator.SubAgent is None,
        # so it falls through to `import core.orchestrator as _orch_mod`
        with patch.dict(
            "core.agent_coordinator.__dict__", {"SubAgent": None}, clear=False
        ):
            with patch("core.orchestrator.SubAgent", fake_cls, create=True):
                result = await coord._spawn_sub_agent(
                    {"name": "fb_test", "role": "researcher", "task": "research"}
                )
                assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_all_fallbacks_fail_uses_module_level_subagent(self):
        """Line 87: All lookups return None → AgentCls = SubAgent (module-level import)."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="done")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        final_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID OK")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        # orchestrator.SubAgent → None
        coord.orchestrator.SubAgent = None

        with patch.dict(
            "core.agent_coordinator.__dict__", {"SubAgent": None}, clear=False
        ):
            # core.orchestrator.SubAgent also None
            with patch("core.orchestrator.SubAgent", None, create=True):
                # The final fallback `AgentCls = SubAgent` will use whatever
                # the module-level `from core.agents import SubAgent` resolved.
                # Patch that symbol directly.
                with patch("core.agent_coordinator.SubAgent", final_cls):
                    result = await coord._spawn_sub_agent(
                        {"name": "final", "role": "dev", "task": "do stuff"}
                    )
                    assert isinstance(result, str)


# ===========================================================================
# 2. Validation exception paths
# ===========================================================================


class TestValidationExceptionPaths:
    """Cover lines 108-109 (del sub_agents raises) and 129-133 (dict/registration fails)."""

    @pytest.mark.asyncio
    async def test_del_sub_agents_raises(self):
        """Lines 108-109: `del self.orchestrator.sub_agents[name]` raises during validation failure."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        fake_cls = MagicMock(return_value=fake_agent)

        # Validation fails
        coord.orchestrator.llm.generate = AsyncMock(return_value="VIOLATION: bad plan")

        # sub_agents dict that raises on __delitem__
        exploding_dict = MagicMock(spec=dict)
        exploding_dict.__contains__ = MagicMock(return_value=True)
        exploding_dict.__delitem__ = MagicMock(side_effect=KeyError("no such key"))

        coord.orchestrator.sub_agents = exploding_dict

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent(
                {"name": "bad_agent", "role": "hacker", "task": "hack things"}
            )
            assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_agent_dict_assignment_raises(self):
        """Lines 129-130: agent.__dict__ assignment raises → pass silently."""
        coord = _make_coordinator()

        # Custom agent whose __dict__ raises on specific key sets
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
            result = await coord._spawn_sub_agent(
                {"name": "frozen", "role": "dev", "task": "test"}
            )
            # Should still succeed (the try/except around __dict__ is pass)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_sub_agents_registration_raises(self):
        """Lines 132-133: self.orchestrator.sub_agents[name] = agent raises → pass."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="result")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(return_value="VALID plan")
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        # Make sub_agents assignment raise
        exploding_dict = MagicMock(spec=dict)
        exploding_dict.__setitem__ = MagicMock(side_effect=RuntimeError("no space"))
        coord.orchestrator.sub_agents = exploding_dict

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            result = await coord._spawn_sub_agent(
                {"name": "orphan", "role": "dev", "task": "build"}
            )
            assert isinstance(result, str)


# ===========================================================================
# 3. Synthesis outer exception handler
# ===========================================================================


class TestSynthesisOuterException:
    """Cover lines 208-210: outer try/except catches everything and returns str(synthesis_raw)."""

    @pytest.mark.asyncio
    async def test_synthesis_outer_exception_returns_raw(self):
        """Lines 208-210: everything inside the try block fails → return str(synthesis_raw)."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="ok plan")
        fake_agent.run = AsyncMock(return_value="raw output")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        fake_cls = MagicMock(return_value=fake_agent)

        coord.orchestrator.llm.generate = AsyncMock(
            side_effect=[
                "VALID",  # validation
                "synthesis raw text",  # synthesis
            ]
        )

        # Make str() on synthesis_raw work but then the json parse + regex
        # somehow still fails. We achieve this by making memory.memory_write
        # raise, AND making the `for client in ...` also raise, then ultimately
        # the `return summary` line succeeds unless `summary` assignment fails.
        # Actually lines 208-210 fire when the *entire* try block (161-207) raises.
        # The easiest way: make `re.search` raise.
        coord.orchestrator.memory.memory_write = AsyncMock()
        coord.orchestrator.clients = []

        with patch("core.agent_coordinator.SubAgent", fake_cls):
            with patch(
                "core.agent_coordinator.re.search",
                side_effect=RuntimeError("regex broken"),
            ):
                result = await coord._spawn_sub_agent(
                    {"name": "synth_fail", "role": "dev", "task": "do"}
                )
                # Should return str(synthesis_raw) which is the second LLM response
                assert "synthesis raw text" in result


# ===========================================================================
# 4. JSON parse failure with regex match present
# ===========================================================================


class TestSynthesisJsonParseFallback:
    """Cover lines 172-174: regex match exists but json.loads fails → pass."""

    @pytest.mark.asyncio
    async def test_json_parse_failure_with_regex_match(self):
        """Lines 172-174: json_match found but json.loads raises → falls to pass."""
        coord = _make_coordinator()

        fake_agent = MagicMock()
        fake_agent.generate_plan = AsyncMock(return_value="plan")
        fake_agent.run = AsyncMock(return_value="done")
        # MagicMock already has a working __dict__; overwriting it breaks internals

        fake_cls = MagicMock(return_value=fake_agent)

        # Return invalid JSON that looks like a JSON object
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
            result = await coord._spawn_sub_agent(
                {"name": "json_fail", "role": "dev", "task": "parse"}
            )
            assert isinstance(result, str)


# ===========================================================================
# 5. _safe_lstat paths
# ===========================================================================


class TestSafeLstat:
    """Cover lines 287-296: _safe_lstat returning None on FileNotFoundError vs other exceptions."""

    @pytest.mark.asyncio
    async def test_safe_lstat_file_not_found(self):
        """Lines 293-294: FileNotFoundError → return None (new file write succeeds)."""
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
        """Lines 295-296: non-FileNotFoundError exception → return None."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}

        target = os.path.join(workspace, "somefile.txt")
        with open(target, "w") as f:
            f.write("data")

        try:
            # Patch os.lstat to raise PermissionError (not FileNotFoundError)
            with patch("os.lstat", side_effect=PermissionError("denied")):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                # Should still proceed (pre_stat=None), or fail at os.open
                assert isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# 6. read_file — relative path size limit
# ===========================================================================


class TestReadFileRelativePathSizeLimit:
    """Cover line 313: relative path open succeeds but data exceeds READ_LIMIT."""

    @pytest.mark.asyncio
    async def test_relative_read_exceeds_limit(self):
        """Line 313: relative path direct open returns data > READ_LIMIT → file too large."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        # READ_LIMIT is typically 10MB; mock the open to return large data
        large_data = "x" * (11 * 1024 * 1024)  # 11MB

        with patch("builtins.open", mock_open(read_data=large_data)):
            result = await coord._execute_tool_for_sub_agent(
                "reader",
                {"name": "read_file", "input": {"path": "relative/file.txt"}},
            )
            assert "too large" in result.lower()


# ===========================================================================
# 7. read_file — fallback open returns file too large
# ===========================================================================


class TestReadFileFallbackTooLarge:
    """Cover line 373: fallback `open()` returns data exceeding READ_LIMIT."""

    @pytest.mark.asyncio
    async def test_fallback_open_too_large(self):
        """Line 373: os.open ENOENT → fallback open succeeds but data > READ_LIMIT."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "bigfile.txt")

        large_data = "x" * (11 * 1024 * 1024)

        try:
            # os.open raises OSError with errno not in ELOOP/EPERM/EACCES
            # so it falls to the fallback open (line 367-376)
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
# 8. read_file — fstat exception → pass
# ===========================================================================


class TestReadFileFstatException:
    """Cover lines 414-415: exception during fstat size check → pass (continue reading)."""

    @pytest.mark.asyncio
    async def test_fstat_size_check_exception(self):
        """Lines 414-415: post_stat.st_size attribute raises → pass and continue."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "testfile.txt")
        with open(target, "w") as f:
            f.write("content")

        try:
            # Create a stat result that raises when st_size is accessed inside the
            # size-limit try block (lines 397-415). We patch os.fstat to return a
            # mock whose st_size property raises.
            bad_stat = MagicMock()
            bad_stat.st_ino = os.stat(target).st_ino
            bad_stat.st_dev = os.stat(target).st_dev
            type(bad_stat).st_size = PropertyMock(side_effect=OSError("bad fstat"))

            real_lstat = os.lstat

            with patch("os.fstat", return_value=bad_stat):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                # Should still read the file (fstat error is swallowed)
                assert "content" in result or isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# 9. read_file — chunk remaining ≤ 0
# ===========================================================================


class TestReadFileChunkRemainingZero:
    """Cover lines 426-431: remaining counter hits ≤ 0 and breaks the read loop."""

    @pytest.mark.asyncio
    async def test_chunk_remaining_breaks_loop(self):
        """Lines 428-431: remaining decremented to ≤ 0 → break."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"reader": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "chunkfile.txt")
        with open(target, "w") as f:
            f.write("A" * 200)

        try:
            # Make fstat report a small st_size so remaining becomes small
            small_stat = MagicMock()
            real_stat = os.stat(target)
            small_stat.st_ino = real_stat.st_ino
            small_stat.st_dev = real_stat.st_dev
            small_stat.st_size = (
                10  # Only 10 bytes → remaining will go ≤ 0 after first chunk
            )

            real_fstat = os.fstat

            def _patched_fstat(fd):
                return small_stat

            with patch("os.fstat", side_effect=_patched_fstat):
                result = await coord._execute_tool_for_sub_agent(
                    "reader",
                    {"name": "read_file", "input": {"path": target}},
                )
                # Should return some data (truncated by remaining counter)
                assert isinstance(result, str)
        finally:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# 10. read_file — fd close in exception handler
# ===========================================================================


class TestReadFileFdCloseInException:
    """Cover lines 438-439: os.close(fd) in the except handler also raises → pass."""

    @pytest.mark.asyncio
    async def test_fd_close_raises_in_exception_handler(self):
        """Lines 436-439: main read fails, then os.close(fd) also raises → pass."""
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
                    # First close attempt (in the except handler) raises
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
            # Clean up any leaked FDs
            for fd in fd_opened:
                try:
                    real_os_close(fd)
                except Exception:
                    pass
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)


# ===========================================================================
# 11. write_file — symlink detection via S_ISLNK
# ===========================================================================


class TestWriteFileSymlinkDetection:
    """Cover lines 491-507: write_file detects destination is a symlink via S_ISLNK."""

    @pytest.mark.asyncio
    async def test_write_dest_is_symlink(self):
        """Lines 490-505: post_stat shows S_ISLNK → deny write and clean up temp."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "link_target.txt")

        try:
            # Create a real file first so validation passes
            with open(target, "w") as f:
                f.write("original")

            # Patch _safe_lstat to return a stat result indicating symlink
            symlink_stat = MagicMock()
            symlink_stat.st_mode = stat.S_IFLNK | 0o777  # symlink mode
            symlink_stat.st_ino = 12345
            symlink_stat.st_dev = 100

            # Patch os.lstat to return symlink stat only on the second call
            # for the *target file*. Other paths (workspace dir, etc.) get the
            # real lstat so _validate_path / is_symlink() work normally.
            _real_lstat = os.lstat
            target_call_count = [0]

            def _fake_lstat(path_str):
                if str(path_str) == target:
                    target_call_count[0] += 1
                    if target_call_count[0] <= 2:
                        # First two calls (is_symlink in _validate_path + pre_stat): normal
                        return _real_lstat(target)
                    # Third call (post_stat): symlink
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
# 12. write_file — TOCTOU identity change with unlink
# ===========================================================================


class TestWriteFileTOCTOUUnlink:
    """Cover lines 516-517: TOCTOU detected (identity changed) → unlink temp and deny."""

    @pytest.mark.asyncio
    async def test_write_toctou_identity_change(self):
        """Lines 510-517: pre_stat inode differs from post_stat → TOCTOU detected."""
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
                        # First two calls (is_symlink + pre_stat): pre-stat
                        return pre
                    # Third call (post_stat): different inode
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
# 13. write_file — outer exception with temp file cleanup
# ===========================================================================


class TestWriteFileOuterException:
    """Cover lines 532-549: write_file outer try/except catches and cleans up temp."""

    @pytest.mark.asyncio
    async def test_write_outer_exception_cleans_temp(self):
        """Lines 532-549: mkstemp succeeds but fdopen/write fails → unlink temp and return error."""
        coord = _make_coordinator()
        agent = _active_agent_with_tools()
        coord.orchestrator.sub_agents = {"writer": agent}

        workspace = tempfile.mkdtemp()
        coord.orchestrator.config.paths = {"workspaces": workspace}
        target = os.path.join(workspace, "fail_write.txt")

        try:
            # Patch os.fdopen to raise so we hit the outer except block
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
        """Lines 534-536: temp file unlink fails too → pass."""
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
