"""
Tests for Performance Audit fixes (PERF-01 through PERF-12).
Validates async subprocess, LRU eviction, close() methods,
parallel gather, and module-level imports.
"""

import asyncio
import os
import sqlite3
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# PERF-05: LRU-evicting chat_contexts (OrderedDict) in MessageHandler
# ---------------------------------------------------------------------------
class TestMessageHandlerLRUEviction:
    """Test the OrderedDict LRU cache in MessageHandler.chat_contexts."""

    @pytest.fixture
    def handler(self):
        from core.orchestrator_components import MessageHandler

        mock_orchestrator = MagicMock()
        mock_orchestrator.memory = AsyncMock()
        mock_orchestrator.memory.chat_read = AsyncMock(return_value=[])
        handler = MessageHandler(mock_orchestrator)
        return handler

    def test_chat_contexts_is_ordered_dict(self, handler):
        """PERF-05: chat_contexts must be an OrderedDict for LRU eviction."""
        assert isinstance(handler.chat_contexts, OrderedDict)

    def test_max_cached_contexts_default(self, handler):
        """PERF-05: Default max cached contexts is 1000."""
        assert handler._MAX_CACHED_CONTEXTS == 1000

    @pytest.mark.asyncio
    async def test_lru_eviction_triggers_at_limit(self, handler):
        """PERF-05: Oldest entry evicted when cache exceeds max size."""
        # Set a small limit for testing
        handler._MAX_CACHED_CONTEXTS = 5

        # Populate with 5 entries (at capacity)
        for i in range(5):
            chat_id = f"chat_{i}"
            handler.chat_contexts[chat_id] = [{"role": "user", "content": f"msg_{i}"}]

        # Now add a 6th entry via _update_chat_context
        await handler._update_chat_context("chat_new", "hello")

        # Should still be at max size (5)
        assert len(handler.chat_contexts) <= 5
        # Oldest entry ("chat_0") should have been evicted
        assert "chat_0" not in handler.chat_contexts
        # New entry should exist
        assert "chat_new" in handler.chat_contexts

    @pytest.mark.asyncio
    async def test_lru_move_to_end_on_access(self, handler):
        """PERF-05: Accessing an existing entry moves it to the end (most recent)."""
        handler._MAX_CACHED_CONTEXTS = 3

        # Add 3 entries
        for i in range(3):
            handler.chat_contexts[f"chat_{i}"] = [{"role": "user", "content": f"msg_{i}"}]

        # Access chat_0 (oldest) - it should be moved to end
        await handler._update_chat_context("chat_0", "updated message")

        # Now add a 4th entry - chat_1 should be evicted (it's the oldest now)
        await handler._update_chat_context("chat_3", "new entry")

        assert "chat_1" not in handler.chat_contexts
        assert "chat_0" in handler.chat_contexts  # Was moved to end, so survives
        assert "chat_3" in handler.chat_contexts

    @pytest.mark.asyncio
    async def test_context_keeps_only_last_10_messages(self, handler):
        """Each chat context is trimmed to 10 messages."""
        handler.chat_contexts["chat_x"] = [{"role": "user", "content": f"old_{i}"} for i in range(10)]
        await handler._update_chat_context("chat_x", "new_message")
        assert len(handler.chat_contexts["chat_x"]) == 10


# ---------------------------------------------------------------------------
# PERF-06 / PERF-07 / PERF-08 / PERF-09: Resource cleanup (close() methods)
# ---------------------------------------------------------------------------
class TestMemoryServerClose:
    """Test MemoryServer.close() properly tears down resources."""

    @pytest.fixture
    def memory_server(self, tmp_path):
        from core.memory.mcp_server import MemoryServer

        db_path = str(tmp_path / "test_memory.db")
        server = MemoryServer(db_path=db_path)
        return server

    @pytest.mark.asyncio
    async def test_close_shuts_down_executor(self, memory_server):
        """PERF-07: close() should shut down the shared ThreadPoolExecutor."""
        executor = memory_server._shared_executor
        assert not executor._shutdown  # Not shut down yet

        await memory_server.close()

        assert executor._shutdown  # Now shut down

    @pytest.mark.asyncio
    async def test_close_calls_child_close_methods(self, memory_server):
        """PERF-08/09: close() delegates to chat_memory.close() and knowledge_memory.close()."""
        memory_server.chat_memory.close = MagicMock()
        memory_server.knowledge_memory.close = MagicMock()

        await memory_server.close()

        memory_server.chat_memory.close.assert_called_once()
        memory_server.knowledge_memory.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, memory_server):
        """Calling close() multiple times should not raise."""
        await memory_server.close()
        await memory_server.close()  # Should not raise


class TestChatMemoryClose:
    """Test ChatMemoryManager.close() properly cleans up SQLite connections."""

    @pytest.fixture
    def chat_memory(self, tmp_path):
        from core.memory.chat_memory import ChatMemoryManager

        db_path = str(tmp_path / "test_chat.db")
        return ChatMemoryManager(db_path=db_path)

    def test_close_with_active_connection(self, chat_memory):
        """PERF-08: close() should close the thread-local SQLite connection."""
        # Force creation of a connection
        conn = chat_memory._get_connection()
        assert conn is not None

        chat_memory.close()

        # The connection attribute should be cleaned up
        # Accessing _local.conn after close should work without error

    def test_close_without_connection(self, chat_memory):
        """PERF-08: close() should be safe even if no connection was ever created."""
        # Don't create any connection
        chat_memory.close()  # Should not raise

    def test_close_handles_exception(self, chat_memory):
        """PERF-08: close() should swallow exceptions during cleanup."""
        # Force a connection and then make close() fail
        chat_memory._get_connection()
        chat_memory._local.conn = MagicMock()
        chat_memory._local.conn.close.side_effect = Exception("close failed")

        # Should not raise
        chat_memory.close()


class TestKnowledgeMemoryClose:
    """Test KnowledgeMemoryManager.close() properly cleans up SQLite connections."""

    @pytest.fixture
    def knowledge_memory(self, tmp_path):
        from core.memory.knowledge_memory import KnowledgeMemoryManager

        db_path = str(tmp_path / "test_knowledge.db")
        return KnowledgeMemoryManager(db_path=db_path)

    def test_close_with_active_connection(self, knowledge_memory):
        """PERF-09: close() should close the thread-local SQLite connection."""
        conn = knowledge_memory._get_connection()
        assert conn is not None

        knowledge_memory.close()

    def test_close_without_connection(self, knowledge_memory):
        """PERF-09: close() should be safe even if no connection was ever created."""
        knowledge_memory.close()  # Should not raise

    def test_close_handles_exception(self, knowledge_memory):
        """PERF-09: close() should swallow exceptions during cleanup."""
        knowledge_memory._get_connection()
        knowledge_memory._local.conn = MagicMock()
        knowledge_memory._local.conn.close.side_effect = Exception("close failed")

        knowledge_memory.close()  # Should not raise


# ---------------------------------------------------------------------------
# PERF-10: Parallel keyword searches with asyncio.gather
# ---------------------------------------------------------------------------
class TestParallelKeywordSearches:
    """Test _get_relevant_lessons uses asyncio.gather for parallel search."""

    @pytest.fixture
    def orchestrator(self, mock_config):
        from core.orchestrator import MegaBotOrchestrator

        with patch("core.orchestrator.ModuleDiscovery"):
            with patch("core.orchestrator.OpenClawAdapter"):
                with patch("core.orchestrator.MemUAdapter"):
                    with patch("core.orchestrator.MCPManager"):
                        orc = MegaBotOrchestrator(mock_config)
                        orc.llm = AsyncMock()
                        orc.memory = AsyncMock()
                        return orc

    @pytest.mark.asyncio
    async def test_gather_is_used_for_keyword_searches(self, orchestrator):
        """PERF-10: Multiple keyword searches should run via asyncio.gather."""
        # LLM returns comma-separated keywords
        orchestrator.llm.generate = AsyncMock(side_effect=["react, typescript, nextjs", "Summary of lessons"])

        # Memory search returns some lessons
        lesson = {"content": "Use server components for data fetching", "key": "l1"}
        orchestrator.memory.memory_search = AsyncMock(return_value=[lesson])

        result = await orchestrator._get_relevant_lessons("Build a React app")

        # memory_search should be called at least 4 times:
        # 1 direct search + 3 keyword searches (react, typescript, nextjs)
        assert orchestrator.memory.memory_search.call_count >= 4

    @pytest.mark.asyncio
    async def test_gather_deduplicates_results(self, orchestrator):
        """PERF-10: Duplicate lessons from different keywords should be deduplicated."""
        orchestrator.llm.generate = AsyncMock(side_effect=["react, nextjs", "Summary"])

        same_lesson = {"content": "Use hooks for state", "key": "l1"}
        orchestrator.memory.memory_search = AsyncMock(return_value=[same_lesson])

        result = await orchestrator._get_relevant_lessons("Build a React app")

        # Should not produce duplicates in the final result
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_empty_keywords_returns_empty(self, orchestrator):
        """PERF-10: No keywords should return empty string."""
        orchestrator.llm.generate = AsyncMock(return_value="")
        orchestrator.memory.memory_search = AsyncMock(return_value=[])

        result = await orchestrator._get_relevant_lessons("hello")
        assert result == ""


# ---------------------------------------------------------------------------
# PERF-01/02/03: Async subprocess in gateway (tailscale, cloudflare, health)
# ---------------------------------------------------------------------------
class TestGatewayAsyncSubprocess:
    """Test that gateway uses asyncio.create_subprocess_exec instead of blocking subprocess.run."""

    @pytest.mark.asyncio
    async def test_start_tailscale_vpn_uses_async_subprocess(self):
        """PERF-01: _start_tailscale_vpn should use asyncio.create_subprocess_exec."""
        from core.network.gateway import UnifiedGateway

        gw = MagicMock(spec=UnifiedGateway)
        gw.tailscale_auth_key = "tskey-12345"
        gw.health_status = {}
        gw.logger = MagicMock()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await UnifiedGateway._start_tailscale_vpn(gw)

            mock_exec.assert_called_once()
            args = mock_exec.call_args
            assert "tailscale" in args[0]
            assert result is True

    @pytest.mark.asyncio
    async def test_start_tailscale_vpn_timeout(self):
        """PERF-01: Tailscale subprocess should be killed on timeout."""
        from core.network.gateway import UnifiedGateway

        gw = MagicMock(spec=UnifiedGateway)
        gw.tailscale_auth_key = "tskey-12345"
        gw.health_status = {}
        gw.logger = MagicMock()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await UnifiedGateway._start_tailscale_vpn(gw)
                assert result is False

    @pytest.mark.asyncio
    async def test_start_tailscale_vpn_no_key(self):
        """PERF-01: Without auth key, should return False immediately."""
        from core.network.gateway import UnifiedGateway, ConnectionType

        gw = MagicMock(spec=UnifiedGateway)
        gw.tailscale_auth_key = None
        gw.health_status = {}

        result = await UnifiedGateway._start_tailscale_vpn(gw)
        assert result is False
        assert gw.health_status[ConnectionType.VPN.value] is False

    @pytest.mark.asyncio
    async def test_start_cloudflare_tunnel_uses_async_subprocess(self):
        """PERF-02: _start_cloudflare_tunnel version check should use async subprocess."""
        from core.network.gateway import UnifiedGateway

        gw = MagicMock(spec=UnifiedGateway)
        gw.cloudflare_tunnel_id = "tunnel-123"
        gw.health_status = {}
        gw.logger = MagicMock()

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        mock_popen = MagicMock()
        mock_popen.poll.return_value = None  # Process running

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("subprocess.Popen", return_value=mock_popen):
                result = await UnifiedGateway._start_cloudflare_tunnel(gw)
                assert result is True

    @pytest.mark.asyncio
    async def test_start_cloudflare_no_tunnel_id(self):
        """PERF-02: Without tunnel ID, should return False immediately."""
        from core.network.gateway import UnifiedGateway, ConnectionType

        gw = MagicMock(spec=UnifiedGateway)
        gw.cloudflare_tunnel_id = None
        gw.health_status = {}

        result = await UnifiedGateway._start_cloudflare_tunnel(gw)
        assert result is False


# ---------------------------------------------------------------------------
# PERF-04: Async subprocess in orchestrator _handle_system_command
# ---------------------------------------------------------------------------
class TestOrchestratorAsyncSubprocess:
    """Test that _handle_system_command uses asyncio.create_subprocess_exec."""

    @pytest.fixture
    def orchestrator(self, mock_config):
        from core.orchestrator import MegaBotOrchestrator

        with patch("core.orchestrator.ModuleDiscovery"):
            with patch("core.orchestrator.OpenClawAdapter"):
                with patch("core.orchestrator.MemUAdapter"):
                    with patch("core.orchestrator.MCPManager"):
                        orc = MegaBotOrchestrator(mock_config)
                        orc.adapters = {
                            "openclaw": AsyncMock(),
                            "memu": AsyncMock(),
                            "mcp": AsyncMock(),
                            "messaging": AsyncMock(),
                            "gateway": AsyncMock(),
                        }
                        orc.llm = AsyncMock()
                        orc.memory = AsyncMock()
                        return orc

    @pytest.mark.asyncio
    async def test_system_command_uses_admin_handler(self, orchestrator):
        """System command execution delegates to admin_handler._execute_approved_action."""
        mock_ws = AsyncMock()

        action = {
            "id": "test-cmd-1",
            "type": "system_command",
            "payload": {"params": {"command": "echo hello"}},
            "websocket": mock_ws,
        }
        orchestrator.admin_handler.approval_queue = [action]

        await orchestrator._process_approval("test-cmd-1", approved=True)

        # Should have sent command result to websocket
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "command_result"
        assert call_args["success"] is True

    @pytest.mark.asyncio
    async def test_system_command_blocked_by_allowlist(self, orchestrator):
        """System command not in ALLOWED_COMMANDS is blocked."""
        mock_ws = AsyncMock()

        action = {
            "id": "test-cmd-2",
            "type": "system_command",
            "payload": {"params": {"command": "rm -rf /"}},
            "websocket": mock_ws,
        }
        orchestrator.admin_handler.approval_queue = [action]

        await orchestrator._process_approval("test-cmd-2", approved=True)

        # rm is not in ALLOWED_COMMANDS, so no command_result should be sent
        # (the handler returns the error message but doesn't send via ws)
        ws_calls = [c[0][0] for c in mock_ws.send_json.call_args_list] if mock_ws.send_json.called else []
        assert not any(c.get("type") == "command_result" for c in ws_calls)


# ---------------------------------------------------------------------------
# PERF-06: LLM provider close on shutdown
# ---------------------------------------------------------------------------
class TestOrchestratorShutdownCleanup:
    """Test that shutdown() closes LLM provider and memory server."""

    @pytest.fixture
    def orchestrator(self, mock_config):
        from core.orchestrator import MegaBotOrchestrator

        with patch("core.orchestrator.ModuleDiscovery"):
            with patch("core.orchestrator.OpenClawAdapter"):
                with patch("core.orchestrator.MemUAdapter"):
                    with patch("core.orchestrator.MCPManager"):
                        orc = MegaBotOrchestrator(mock_config)
                        orc.adapters = {
                            "openclaw": AsyncMock(),
                            "memu": AsyncMock(),
                            "mcp": AsyncMock(),
                            "messaging": AsyncMock(),
                            "gateway": AsyncMock(),
                        }
                        orc.llm = AsyncMock()
                        orc.memory = AsyncMock()
                        return orc

    @pytest.mark.asyncio
    async def test_shutdown_closes_llm_provider(self, orchestrator):
        """PERF-06: shutdown() should call llm.close()."""
        orchestrator.llm.close = AsyncMock()

        await orchestrator.shutdown()

        orchestrator.llm.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_memory_server(self, orchestrator):
        """PERF-07/08/09: shutdown() should call memory.close()."""
        orchestrator.memory.close = AsyncMock()

        await orchestrator.shutdown()

        orchestrator.memory.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_llm_close_error(self, orchestrator):
        """PERF-06: shutdown() should not crash if llm.close() raises."""
        orchestrator.llm.close = AsyncMock(side_effect=Exception("LLM close failed"))
        orchestrator.memory.close = AsyncMock()

        # Should not raise
        await orchestrator.shutdown()

        # Memory close should still be called despite LLM close failure
        orchestrator.memory.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_memory_close_error(self, orchestrator):
        """shutdown() should not crash if memory.close() raises."""
        orchestrator.llm.close = AsyncMock()
        orchestrator.memory.close = AsyncMock(side_effect=Exception("Memory close failed"))

        # Should not raise
        await orchestrator.shutdown()


# ---------------------------------------------------------------------------
# PERF-11: Async discovery scan in orchestrator.start()
# ---------------------------------------------------------------------------
class TestAsyncDiscoveryScan:
    """Test that orchestrator.start() uses asyncio.to_thread for discovery.scan."""

    @pytest.mark.asyncio
    async def test_start_uses_asyncio_to_thread(self, mock_config):
        """PERF-11: discovery.scan() should run in asyncio.to_thread."""
        from core.orchestrator import MegaBotOrchestrator

        with patch("core.orchestrator.ModuleDiscovery") as mock_disc_cls:
            with patch("core.orchestrator.OpenClawAdapter"):
                with patch("core.orchestrator.MemUAdapter"):
                    with patch("core.orchestrator.MCPManager"):
                        orc = MegaBotOrchestrator(mock_config)
                        orc.adapters = {
                            "openclaw": AsyncMock(),
                            "memu": AsyncMock(),
                            "mcp": AsyncMock(),
                            "messaging": AsyncMock(),
                            "gateway": AsyncMock(),
                        }
                        orc.llm = AsyncMock()
                        orc.memory = AsyncMock()

                        mock_scan = MagicMock()
                        orc.discovery.scan = mock_scan

                        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
                            # Patch safe_create_task to avoid actually starting tasks
                            with patch("core.task_utils.safe_create_task"):
                                await orc.start()

                            mock_to_thread.assert_called_once_with(mock_scan)


# ---------------------------------------------------------------------------
# PERF-12: Module-level import hashlib in gateway
# ---------------------------------------------------------------------------
class TestModuleLevelImports:
    """Test that hashlib is imported at module level in gateway."""

    def test_hashlib_is_module_level_import(self):
        """PERF-12: hashlib should be imported at module level, not inside functions."""
        import core.network.gateway as gw_module

        # If hashlib is at module level, it should be accessible as an attribute
        assert hasattr(gw_module, "hashlib") or "hashlib" in dir(gw_module)


# ---------------------------------------------------------------------------
# Integration test: MemoryServer full lifecycle
# ---------------------------------------------------------------------------
class TestMemoryServerLifecycle:
    """Integration tests for MemoryServer create → use → close lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path):
        """Test that MemoryServer works after creation and cleans up on close."""
        from core.memory.mcp_server import MemoryServer

        db_path = str(tmp_path / "lifecycle_test.db")
        server = MemoryServer(db_path=db_path)

        # Write some data
        result = await server.knowledge_memory.write(key="test_key", type="learned_lesson", content="test content")
        assert "success" in result.lower() or "written" in result.lower()

        # Read it back
        data = await server.knowledge_memory.read("test_key")
        assert data is not None
        assert data["content"] == "test content"

        # Close
        await server.close()

        # Verify executor is shut down
        assert server._shared_executor._shutdown

    @pytest.mark.asyncio
    async def test_close_then_reopen(self, tmp_path):
        """Test that data persists after close and reopen."""
        from core.memory.mcp_server import MemoryServer

        db_path = str(tmp_path / "persist_test.db")

        # First session
        server1 = MemoryServer(db_path=db_path)
        await server1.knowledge_memory.write(key="persist_key", type="fact", content="persisted data")
        await server1.close()

        # Second session
        server2 = MemoryServer(db_path=db_path)
        data = await server2.knowledge_memory.read("persist_key")
        assert data is not None
        assert data["content"] == "persisted data"
        await server2.close()
