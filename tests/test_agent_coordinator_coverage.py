"""Additional coverage tests for core/agent_coordinator.py.

Targets uncovered lines: _audit exception path, _spawn_sub_agent fallback
paths, _validate_path edge cases, read_file fd-based flow, write_file TOCTOU,
query_rag, MCP fallback with error dict.
"""

import errno
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent_coordinator import AgentCoordinator, _audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coord(orch):
    return AgentCoordinator(orch)


def _active_agent(**overrides):
    """Return a MagicMock configured as an active sub-agent."""
    m = MagicMock()
    m.role = overrides.get("role", "Tester")
    m._active = True
    m._get_sub_tools.return_value = overrides.get("tools", [])
    return m


# ---------------------------------------------------------------------------
# _audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_audit_success(self):
        """Normal audit call should not raise."""
        _audit("test.event", key="value")

    def test_audit_json_serialization_failure(self):
        """When data is not JSON-serializable, _audit silently catches."""
        # A set is not JSON-serializable
        _audit("bad.event", data={1, 2, 3})


# ---------------------------------------------------------------------------
# _spawn_sub_agent — AgentCls resolution fallback paths
# ---------------------------------------------------------------------------


class TestSpawnSubAgentFallbacks:
    @pytest.mark.asyncio
    async def test_globals_subagent_none_falls_back_to_orchestrator(self, orchestrator):
        """When globals()['SubAgent'] is None, use orchestrator.SubAgent."""
        coord = _make_coord(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}']
        )
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        mock_cls = MagicMock(return_value=mock_agent)
        # Patch globals()["SubAgent"] to None so it tries orchestrator attr
        with patch.dict("core.agent_coordinator.__dict__", {"SubAgent": None}):
            orchestrator.SubAgent = mock_cls
            res = await coord._spawn_sub_agent({"name": "fb1", "task": "t"})
        assert isinstance(res, str)
        mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_deletes_pre_registered_agent(self, orchestrator):
        """If agent name already in sub_agents when validation fails, it should be removed."""
        coord = _make_coord(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="bad plan")
        mock_agent.run = AsyncMock()

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(return_value="DENIED")

        # Pre-register the agent name
        orchestrator.sub_agents["pre_reg"] = "placeholder"

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "pre_reg", "task": "t"})

        assert "blocked by pre-flight" in res
        assert "pre_reg" not in orchestrator.sub_agents

    @pytest.mark.asyncio
    async def test_synthesis_json_parse_failure_fallback(self, orchestrator):
        """When synthesis output has no valid JSON, summary falls back to raw string."""
        coord = _make_coord(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result data")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", "no json here at all"]
        )
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "nj", "task": "t"})
        # Falls back to the raw synthesis string
        assert "no json here at all" in res

    @pytest.mark.asyncio
    async def test_client_notification_failure(self, orchestrator):
        """Client notification failure should not break synthesis."""
        coord = _make_coord(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", '{"summary":"good","learned_lesson":"L"}']
        )
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock()

        # Set up a client that throws on send_json
        bad_client = MagicMock()
        bad_client.send_json = AsyncMock(side_effect=Exception("ws error"))
        orchestrator.clients = [bad_client]

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "cn", "task": "t"})
        assert "good" in res

    @pytest.mark.asyncio
    async def test_memory_write_failure(self, orchestrator):
        """Memory write failure should not break synthesis return."""
        coord = _make_coord(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", '{"summary":"s","learned_lesson":"L"}']
        )
        orchestrator.memory = MagicMock()
        orchestrator.memory.memory_write = AsyncMock(side_effect=Exception("db err"))

        with patch("core.agent_coordinator.SubAgent", return_value=mock_agent):
            res = await coord._spawn_sub_agent({"name": "mf", "task": "t"})
        assert isinstance(res, str)


# ---------------------------------------------------------------------------
# _validate_path edge cases
# ---------------------------------------------------------------------------


class TestValidatePath:
    @pytest.mark.asyncio
    async def test_empty_path(self, orchestrator, tmp_path):
        """An empty path should be rejected."""
        coord = _make_coord(orchestrator)
        orchestrator.config.paths["workspaces"] = str(tmp_path)

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "read_file", "input": {"path": ""}}
        )
        # Empty path on relative branch tries open("") which fails, then
        # falls through to _validate_path which returns "Empty path"
        assert "denied" in res.lower() or "error" in res.lower()

    @pytest.mark.asyncio
    async def test_path_resolution_error(self, orchestrator, tmp_path):
        """A path that can't be resolved should return an error."""
        coord = _make_coord(orchestrator)
        orchestrator.config.paths["workspaces"] = str(tmp_path)

        agent = _active_agent(tools=[{"name": "write_file", "scope": "fs.write"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        # Use a null byte in the path which should cause a resolution error
        res = await coord._execute_tool_for_sub_agent(
            "a",
            {"name": "write_file", "input": {"path": "/tmp/\x00bad", "content": "x"}},
        )
        assert "Error" in res or "error" in res


# ---------------------------------------------------------------------------
# read_file — relative path direct open
# ---------------------------------------------------------------------------


class TestReadFileRelative:
    @pytest.mark.asyncio
    async def test_relative_path_direct_open(self, orchestrator, tmp_path):
        """A relative path should be opened directly first."""
        coord = _make_coord(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        test_file = workspace / "hello.txt"
        test_file.write_text("hello world")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        # Use a relative path; patch open to control the behavior
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(read=MagicMock(return_value="file content"))
            )
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            res = await coord._execute_tool_for_sub_agent(
                "a", {"name": "read_file", "input": {"path": "hello.txt"}}
            )
        assert res == "file content"


# ---------------------------------------------------------------------------
# read_file — OSError fallback (non-ELOOP)
# ---------------------------------------------------------------------------


class TestReadFileOSErrorFallback:
    @pytest.mark.asyncio
    async def test_os_open_non_eloop_fallback(self, orchestrator, tmp_path):
        """When os.open fails with non-ELOOP error, fallback to builtin open."""
        coord = _make_coord(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "file.txt"
        target.write_text("content via fallback")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        # Make os.open raise ENOENT (not ELOOP/EPERM/EACCES) to trigger fallback
        with patch("os.open", side_effect=OSError(errno.ENOENT, "No such file")):
            res = await coord._execute_tool_for_sub_agent(
                "a", {"name": "read_file", "input": {"path": str(target)}}
            )
        assert "content via fallback" in res

    @pytest.mark.asyncio
    async def test_os_open_non_eloop_fallback_also_fails(self, orchestrator, tmp_path):
        """When both os.open and builtin open fail, return error."""
        coord = _make_coord(orchestrator)
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


# ---------------------------------------------------------------------------
# read_file — fd-based reading: file too large, chunk reading, exception
# ---------------------------------------------------------------------------


class TestReadFileFdBased:
    @pytest.mark.asyncio
    async def test_fd_file_too_large(self, orchestrator, tmp_path):
        """Files exceeding READ_LIMIT via fstat should be rejected."""
        coord = _make_coord(orchestrator)
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

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "read_file", "input": {"path": str(big_file)}}
        )
        assert "too large" in res

    @pytest.mark.asyncio
    async def test_fd_successful_chunk_read(self, orchestrator, tmp_path):
        """Normal fd-based read should return file content."""
        coord = _make_coord(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "good.txt"
        target.write_text("hello from fd")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "read_file", "input": {"path": str(target)}}
        )
        assert "hello from fd" in res

    @pytest.mark.asyncio
    async def test_fd_exception_during_read(self, orchestrator, tmp_path):
        """Exception after fd is opened should be caught and fd closed."""
        coord = _make_coord(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "err.txt"
        target.write_text("x")

        agent = _active_agent(tools=[{"name": "read_file", "scope": "fs.read"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        # Let os.open succeed, then fstat raises
        real_open = os.open
        call_count = 0

        def patched_open(p, flags, *args, **kwargs):
            return real_open(p, flags, *args, **kwargs)

        with patch("os.fstat", side_effect=Exception("fstat boom")):
            res = await coord._execute_tool_for_sub_agent(
                "a", {"name": "read_file", "input": {"path": str(target)}}
            )
        assert "denied" in res.lower() or "fstat boom" in res


# ---------------------------------------------------------------------------
# write_file — TOCTOU detection and exception during write
# ---------------------------------------------------------------------------


class TestWriteFileToctou:
    @pytest.mark.asyncio
    async def test_write_toctou_inode_change(self, orchestrator, tmp_path):
        """Write should be denied if inode changes between pre and post stat."""
        coord = _make_coord(orchestrator)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        orchestrator.config.paths["workspaces"] = str(workspace)

        target = workspace / "toctou.txt"
        target.write_text("original")

        agent = _active_agent(tools=[{"name": "write_file", "scope": "fs.write"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True

        # os.lstat is called on the target path 3 times:
        #   1) candidate.is_symlink() inside _validate_path
        #   2) _safe_lstat(resolved) for pre_stat — before writing
        #   3) _safe_lstat(resolved) for post_stat — after writing temp
        # We need call 3 to return a different inode than call 2 to
        # trigger the TOCTOU check (pre_stat.st_ino != post_stat.st_ino).
        real_lstat = os.lstat
        target_str = str(target.resolve())
        target_call_count = [0]

        def mock_lstat(p):
            s = real_lstat(p)
            if str(p) == target_str:
                target_call_count[0] += 1
                if target_call_count[0] >= 3:
                    # Return modified stat with different inode for post_stat
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
        coord = _make_coord(orchestrator)
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


# ---------------------------------------------------------------------------
# query_rag
# ---------------------------------------------------------------------------


class TestQueryRag:
    @pytest.mark.asyncio
    async def test_query_rag_tool(self, orchestrator):
        """query_rag should call orchestrator.rag.navigate."""
        coord = _make_coord(orchestrator)

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


# ---------------------------------------------------------------------------
# MCP fallback — dict with error key
# ---------------------------------------------------------------------------


class TestMCPFallback:
    @pytest.mark.asyncio
    async def test_mcp_returns_error_dict(self, orchestrator):
        """MCP returning a dict with 'error' key should map to 'not implemented'."""
        coord = _make_coord(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(
            return_value={"error": "tool not found"}
        )

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "custom_tool", "input": {}}
        )
        assert "logic not implemented" in res

    @pytest.mark.asyncio
    async def test_mcp_returns_errors_dict(self, orchestrator):
        """MCP returning a dict with 'errors' key should map to 'not implemented'."""
        coord = _make_coord(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(
            return_value={"errors": ["oops"]}
        )

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "custom_tool", "input": {}}
        )
        assert "logic not implemented" in res

    @pytest.mark.asyncio
    async def test_mcp_returns_success(self, orchestrator):
        """MCP returning a normal result should be passed through."""
        coord = _make_coord(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters["mcp"] = MagicMock()
        orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value="mcp ok")

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "custom_tool", "input": {}}
        )
        assert res == "mcp ok"

    @pytest.mark.asyncio
    async def test_no_mcp_returns_not_implemented(self, orchestrator):
        """Without MCP adapter, unknown tools return 'not implemented'."""
        coord = _make_coord(orchestrator)

        agent = _active_agent(tools=[{"name": "custom_tool", "scope": "custom"}])
        orchestrator.sub_agents = {"a": agent}
        orchestrator.permissions = MagicMock()
        orchestrator.permissions.is_authorized.return_value = True
        orchestrator.adapters.pop("mcp", None)

        res = await coord._execute_tool_for_sub_agent(
            "a", {"name": "custom_tool", "input": {}}
        )
        assert "logic not implemented" in res
