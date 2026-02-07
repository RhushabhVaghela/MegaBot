"""Phase 4 coverage tests — targeting specific uncovered lines across the codebase.

Covers:
1. adapters/messaging/server.py lines 104, 113  (missing env vars → ValueError)
2. core/agent_coordinator.py lines 75-76, 83-84 (SubAgent resolution fallbacks)
3. core/agent_coordinator.py lines 287-288       (outer path validation exception)
4. core/agent_coordinator.py line 426             (read_file empty file → break)
5. core/agent_coordinator.py lines 493-494, 506-507, 516-517  (write_file TOCTOU passes)
6. core/network/gateway.py lines 482-491, 539-588 (auth flow + _authenticate_connection)
7. features/dash_data/agent.py line 230           (blocked pattern detection)
"""

import json
import os
import stat as _stat
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. SecureWebSocket — missing env vars
# ---------------------------------------------------------------------------


class TestSecureWebSocketMissingEnvVars:
    """Cover server.py lines 104 and 113."""

    def test_missing_ws_password_raises(self):
        """Line 104: ValueError when MEGABOT_WS_PASSWORD is unset and no arg."""
        saved_pw = os.environ.pop("MEGABOT_WS_PASSWORD", None)
        saved_salt = os.environ.pop("MEGABOT_ENCRYPTION_SALT", None)
        try:
            from adapters.messaging.server import SecureWebSocket

            with pytest.raises(ValueError, match="MEGABOT_WS_PASSWORD must be set"):
                SecureWebSocket(password=None)
        finally:
            # Restore both env vars so other tests aren't broken
            if saved_pw is not None:
                os.environ["MEGABOT_WS_PASSWORD"] = saved_pw
            if saved_salt is not None:
                os.environ["MEGABOT_ENCRYPTION_SALT"] = saved_salt

    def test_missing_encryption_salt_raises(self):
        """Line 113: ValueError when MEGABOT_ENCRYPTION_SALT is unset."""
        saved_salt = os.environ.pop("MEGABOT_ENCRYPTION_SALT", None)
        try:
            from adapters.messaging.server import SecureWebSocket

            with pytest.raises(ValueError, match="MEGABOT_ENCRYPTION_SALT must be set"):
                # Provide password so we pass line 104 but fail at line 113
                SecureWebSocket(password="some-password")
        finally:
            if saved_salt is not None:
                os.environ["MEGABOT_ENCRYPTION_SALT"] = saved_salt


# ---------------------------------------------------------------------------
# 2. AgentCoordinator — SubAgent resolution exception fallbacks
# ---------------------------------------------------------------------------


class TestSubAgentResolutionFallbacks:
    """Cover agent_coordinator.py lines 75-76 and 83-84."""

    @pytest.mark.asyncio
    async def test_subagent_resolution_lines_75_76(self, orchestrator):
        """Lines 75-76: getattr(self.orchestrator, 'SubAgent') raises → AgentCls = None.

        Flow:
          L71: globals().get("SubAgent") → None  (we patch module dict)
          L73: getattr(self.orchestrator, "SubAgent") → raises  (proxy)
          L75-76: except → AgentCls = None  ← THIS IS WHAT WE COVER
          L78-84: import core.orchestrator, getattr → still None (no attr)
          L87: AgentCls = SubAgent  (module-level import, we patch this)
        """
        from core.agent_coordinator import AgentCoordinator

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="raw result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}']
        )
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

        # 1. Set module-level SubAgent to None → globals().get("SubAgent") returns None
        original_sub = _ac_mod.__dict__.get("SubAgent")
        _ac_mod.__dict__["SubAgent"] = None

        # We need a mock constructor to use at line 87 (final fallback).
        # We'll patch it back as the module-level SubAgent ONLY at line 87,
        # while keeping it None for the globals().get() call at line 71.
        # The trick: patch the final fallback at line 87 via a side-effect
        # that swaps it in after the globals check fails.
        mock_constructor = MagicMock(return_value=mock_agent)

        try:
            # The flow is: globals().get → None, getattr(orch) → raises,
            # import core.orchestrator → no SubAgent attr → None,
            # final fallback: AgentCls = SubAgent (line 87).
            # At line 87, "SubAgent" resolves to _ac_mod.SubAgent (module global).
            # But we set it to None! So we need it to be a real class by line 87.
            # Solution: patch via a custom globals() that returns None for
            # SubAgent on the first call, but let the real module dict have
            # the mock constructor for line 87.
            #
            # Simpler approach: we only need lines 75-76 covered. After that,
            # the code can succeed via any path. Let's set SubAgent = None,
            # make getattr raise (proxy), and then have core.orchestrator
            # provide a valid SubAgent for lines 78-82.
            import core.orchestrator as _orch_mod

            _orch_mod.SubAgent = mock_constructor
            try:
                res = await coord_proxied._spawn_sub_agent(
                    {"name": "test_agent", "task": "test_task"}
                )
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
        """Lines 83-84: import core.orchestrator raises → AgentCls = None, fallback to module-level SubAgent."""
        from core.agent_coordinator import AgentCoordinator

        coord = AgentCoordinator(orchestrator)

        mock_agent = MagicMock()
        mock_agent.generate_plan = AsyncMock(return_value="plan")
        mock_agent.run = AsyncMock(return_value="raw result")

        orchestrator.llm = MagicMock()
        orchestrator.llm.generate = AsyncMock(
            side_effect=["VALID", '{"summary":"ok","learned_lesson":"lesson"}']
        )
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
                    res = await coord_proxied._spawn_sub_agent(
                        {"name": "test_agent2", "task": "test_task2"}
                    )
                    assert isinstance(res, str)


# ---------------------------------------------------------------------------
# 3. AgentCoordinator — outer path validation exception (lines 287-288)
# ---------------------------------------------------------------------------


class TestPathValidationOuterException:
    """Cover agent_coordinator.py lines 287-288."""

    @pytest.mark.asyncio
    async def test_path_validation_outer_exception(self, orchestrator, tmp_path):
        """Lines 287-288: unexpected exception in _validate_and_resolve_path."""
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

        # We need to trigger an exception in the outer try block of _validate_path.
        # The code does: workspace = Path(self.orchestrator.config.paths.get(...)).resolve()
        # We can replace config.paths with a mock dict whose .get raises.
        bomb_dict = MagicMock()
        bomb_dict.get = MagicMock(
            side_effect=RuntimeError("Simulated path config explosion")
        )
        orch.config.paths = bomb_dict

        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {"name": "read_file", "input": {"path": "/some/absolute/path.txt"}},
        )
        assert "Path validation error" in res


# ---------------------------------------------------------------------------
# 4. AgentCoordinator — read_file empty file (line 426)
# ---------------------------------------------------------------------------


class TestReadFileEmptyFile:
    """Cover agent_coordinator.py line 426."""

    @pytest.mark.asyncio
    async def test_read_file_empty_file_breaks_loop(self, orchestrator, tmp_path):
        """Line 426: os.read() returns empty bytes → break."""
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
# 5. AgentCoordinator — write_file TOCTOU pass blocks (lines 493-494, 506-507, 516-517)
# ---------------------------------------------------------------------------


class TestWriteFileTOCTOUPassBlocks:
    """Cover agent_coordinator.py lines 493-494, 506-507, 516-517."""

    @pytest.mark.asyncio
    async def test_unlink_fails_after_inode_mismatch_lines_516_517(
        self, orchestrator, tmp_path
    ):
        """Lines 516-517: os.unlink(tmp_path) fails after inode/dev mismatch → pass.

        The write_file flow calls _safe_lstat twice on the dest path:
          Line 475: pre_stat = _safe_lstat(str(resolved))   ← first call
          Line 486: post_stat = _safe_lstat(str(resolved))  ← second call
        But os.lstat may also be called earlier during path validation
        (candidate.is_symlink() on line 278). We use a phase flag toggled
        after tempfile.mkstemp runs (indicating we're in the write phase)
        to distinguish pre_stat from post_stat.
        """
        from core.agent_coordinator import AgentCoordinator

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
        # capture phase. The next lstat call on dest is the post_stat.
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
                    # Before write phase: return pre_stat (line 475)
                    return PreStat()
                else:
                    # After write phase: return post_stat (line 486)
                    return PostStat()
            return orig_lstat(path)

        def fake_unlink(path):
            # Fail all unlinks to cover lines 516-517 (the except: pass block)
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


# ---------------------------------------------------------------------------
# 6. Gateway — authentication flow + _authenticate_connection
# ---------------------------------------------------------------------------


class TestGatewayAuthentication:
    """Cover gateway.py lines 482-491 and 539-588."""

    def _make_gateway(self, auth_token="secret-token"):
        from core.network.gateway import UnifiedGateway

        return UnifiedGateway(
            megabot_server_port=18799,
            enable_cloudflare=False,
            enable_vpn=False,
            enable_direct_https=False,
            auth_token=auth_token,
        )

    def _make_conn(self, ws, conn_type=None):
        from core.network.gateway import ClientConnection, ConnectionType

        if conn_type is None:
            conn_type = ConnectionType.DIRECT  # non-LOCAL so auth is required
        return ClientConnection(
            websocket=ws,
            connection_type=conn_type,
            client_id="test-client-1",
            ip_address="10.0.0.1",
            connected_at=datetime.now(),
            authenticated=False,
            user_agent="test",
        )

    @pytest.mark.asyncio
    async def test_auth_success_full_flow(self):
        """Lines 539-587: successful authentication with valid token."""
        gw = self._make_gateway(auth_token="my-secret-token")

        # Create a mock websocket that yields an auth message
        auth_msg = json.dumps({"type": "auth", "token": "my-secret-token"})

        ws = AsyncMock()
        # __aiter__ must return an async iterator. We set up __anext__ to
        # return the auth payload once, then StopAsyncIteration.
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        # Auth succeeds — the send_str OSError is silently caught, result is still True
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_wrong_type_field(self):
        """Lines 565-566: type != 'auth' returns False."""
        gw = self._make_gateway(auth_token="token")

        auth_msg = json.dumps({"type": "not_auth", "token": "token"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_missing_token_field(self):
        """Lines 568-570: missing/empty token returns False."""
        gw = self._make_gateway(auth_token="token")

        auth_msg = json.dumps({"type": "auth"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_bytes_payload(self):
        """Lines 555-556: bytes payload decoded properly."""
        gw = self._make_gateway(auth_token="byte-token")

        auth_msg = json.dumps({"type": "auth", "token": "byte-token"}).encode("utf-8")
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_with_data_attribute(self):
        """Lines 553-554: raw message with .data attribute."""
        gw = self._make_gateway(auth_token="data-token")

        raw_msg = MagicMock()
        raw_msg.data = json.dumps({"type": "auth", "token": "data-token"})
        ws = AsyncMock()
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=raw_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)
        ws.send = AsyncMock()

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_send_str_fallback(self):
        """Lines 582-586: ws has send_str but not send."""
        gw = self._make_gateway(auth_token="str-token")

        auth_msg = json.dumps({"type": "auth", "token": "str-token"})

        # Custom mock: has send_str but NOT send, and supports async iteration
        class NoSendWebSocket:
            def __init__(self):
                self.send_str = AsyncMock()
                self._auth_msg = auth_msg

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._auth_msg is not None:
                    msg = self._auth_msg
                    self._auth_msg = None  # Only yield once
                    return msg
                raise StopAsyncIteration

        ws = NoSendWebSocket()
        assert not hasattr(ws, "send")

        conn = self._make_conn(ws)
        result = await gw._authenticate_connection(conn)
        assert result is True
        ws.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_manage_connection_auth_failed_line_484_487(self):
        """Lines 484-487: _authenticate_connection returns False → send error, remove client."""
        gw = self._make_gateway(auth_token="token")

        ws = AsyncMock()
        ws.send = AsyncMock()
        # Make it so auth fails (wrong token)
        auth_msg = json.dumps({"type": "auth", "token": "WRONG"})
        aiter_mock = AsyncMock()
        aiter_mock.__anext__ = AsyncMock(return_value=auth_msg)
        ws.__aiter__ = MagicMock(return_value=aiter_mock)

        conn = self._make_conn(ws)
        await gw._manage_connection(conn)

        # Client should be removed after failed auth
        assert conn.client_id not in gw.clients

    @pytest.mark.asyncio
    async def test_manage_connection_auth_exception_line_488_491(self):
        """Lines 488-491: _authenticate_connection raises → send 'Authentication timeout', remove client."""
        gw = self._make_gateway(auth_token="token")

        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.__aiter__ = MagicMock(
            return_value=MagicMock(
                __anext__=AsyncMock(side_effect=RuntimeError("kaboom"))
            )
        )

        conn = self._make_conn(ws)

        # Patch _authenticate_connection to raise
        with patch.object(
            gw, "_authenticate_connection", side_effect=RuntimeError("kaboom")
        ):
            await gw._manage_connection(conn)

        # Client should have been removed
        assert conn.client_id not in gw.clients


# ---------------------------------------------------------------------------
# 7. DashDataAgent — blocked pattern detection (line 230)
# ---------------------------------------------------------------------------


class TestDashDataBlockedPatterns:
    """Cover features/dash_data/agent.py line 230."""

    @pytest.fixture
    def agent(self):
        llm = AsyncMock(spec=[])
        llm.generate = AsyncMock(return_value="result")
        from features.dash_data.agent import DashDataAgent

        a = DashDataAgent(llm=llm)
        # Pre-load a dataset so execute_python_analysis doesn't bail early
        a.datasets["test_ds"] = [{"x": 1}, {"x": 2}]
        return a

    @pytest.mark.asyncio
    async def test_blocked_import_os(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import os\nos.listdir()")
        assert "Blocked pattern" in res
        assert "__import__" in res or "os." in res

    @pytest.mark.asyncio
    async def test_blocked_eval(self, agent):
        res = await agent.execute_python_analysis("test_ds", "eval('1+1')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_exec(self, agent):
        res = await agent.execute_python_analysis("test_ds", "exec('x=1')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_subprocess(self, agent):
        res = await agent.execute_python_analysis(
            "test_ds", "import subprocess\nsubprocess.run(['ls'])"
        )
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_open(self, agent):
        res = await agent.execute_python_analysis("test_ds", "f = open('/etc/passwd')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_getattr(self, agent):
        res = await agent.execute_python_analysis(
            "test_ds", "getattr(data, '__class__')"
        )
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_compile(self, agent):
        res = await agent.execute_python_analysis(
            "test_ds", "compile('1+1', '<str>', 'eval')"
        )
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_dunder_import(self, agent):
        res = await agent.execute_python_analysis("test_ds", "__import__('os')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_importlib(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import importlib")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_sys_dot(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import sys\nsys.exit()")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_subclasses(self, agent):
        res = await agent.execute_python_analysis(
            "test_ds", "''.__class__.__subclasses__()"
        )
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_globals_dunder(self, agent):
        res = await agent.execute_python_analysis("test_ds", "print(__globals__)")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_builtins_dunder(self, agent):
        res = await agent.execute_python_analysis("test_ds", "print(__builtins__)")
        assert "Blocked pattern" in res


# ── Additional gateway auth edge-case tests (lines 558, 580-581, 585-586) ──


class TestGatewayAuthEdgeCases:
    """Cover remaining uncovered branches in _authenticate_connection."""

    @pytest.mark.asyncio
    async def test_auth_non_string_payload_line_558(self):
        """Line 558/562: raw is an integer (not str/bytes, no .data attr) → str() fallback."""
        from core.network.gateway import (
            ClientConnection,
            ConnectionType,
            UnifiedGateway,
        )

        gw = UnifiedGateway.__new__(UnifiedGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 1

        # The raw value returned by __anext__ is an integer — not str, not bytes
        # json.loads(str(42)) will fail with JSONDecodeError → return False
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=ws)
        ws.__anext__ = AsyncMock(return_value=42)

        conn = ClientConnection(
            client_id="test-edge",
            websocket=ws,
            connection_type=ConnectionType.DIRECT,
            ip_address="10.0.0.1",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_send_raises_exception_lines_580_581(self):
        """Lines 580-581: ws.send() raises during ack → silently ignored, still returns True."""
        from core.network.gateway import (
            ClientConnection,
            ConnectionType,
            UnifiedGateway,
        )

        gw = UnifiedGateway.__new__(UnifiedGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 5

        auth_msg = json.dumps({"type": "auth", "token": "secret"})

        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=ws)
        ws.__anext__ = AsyncMock(return_value=auth_msg)
        ws.send = AsyncMock(side_effect=ConnectionError("broken pipe"))

        conn = ClientConnection(
            client_id="test-send-fail",
            websocket=ws,
            connection_type=ConnectionType.DIRECT,
            ip_address="10.0.0.2",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        assert result is True
        assert conn.authenticated is True
        ws.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_send_str_raises_exception_lines_585_586(self):
        """Lines 585-586: ws.send_str() raises during ack → silently ignored, still returns True."""
        from core.network.gateway import (
            ClientConnection,
            ConnectionType,
            UnifiedGateway,
        )

        gw = UnifiedGateway.__new__(UnifiedGateway)
        gw.auth_token = "secret"
        gw._AUTH_TIMEOUT_SECONDS = 5

        auth_msg = json.dumps({"type": "auth", "token": "secret"})

        # Create a ws object that does NOT have 'send' but DOES have 'send_str'
        class NoSendWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                return auth_msg

            async def send_str(self, data):
                raise OSError("transport closed")

        ws = NoSendWS()

        conn = ClientConnection(
            client_id="test-send-str-fail",
            websocket=ws,
            connection_type=ConnectionType.DIRECT,
            ip_address="10.0.0.3",
            connected_at=datetime.now(),
        )

        result = await gw._authenticate_connection(conn)
        # Auth succeeds — send_str OSError is silently caught, doesn't prevent auth
        assert result is True
