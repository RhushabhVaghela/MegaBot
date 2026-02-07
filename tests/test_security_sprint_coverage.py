"""
Coverage tests for security sprint fixes:
- Write-file post-replace TOCTOU verification
- Write-file S_ISLNK exception path
- Gateway _cleanup_rate_limits
- Gateway health monitor rate-limit sweep
- Gateway _authenticate_connection edge cases
- AST validator edge cases (dash_data sandbox)
- Orchestrator _safe_ws_send edge cases
"""

import asyncio
import json
import os
import stat as _stat
import tempfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Write-file: post-replace TOCTOU (symlink appears AFTER os.replace)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_post_replace_symlink_detected(orchestrator, tmp_path):
    """After os.replace, if destination is now a symlink, deny and unlink."""
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

    dest = tmp_path / "post_replace.txt"

    # We need:
    #  - pre-lstat: returns None (file doesn't exist yet) on first call
    #  - post-lstat (before replace): returns None (still doesn't exist)
    #  - final-lstat (after replace): returns stat with S_ISLNK=True
    orig_lstat = os.lstat
    orig_replace = os.replace
    call_count = {"lstat": 0}

    symlink_stat = SimpleNamespace(st_mode=0o120777, st_ino=99, st_dev=1)

    def fake_lstat(path):
        if str(path) == str(dest):
            call_count["lstat"] += 1
            if call_count["lstat"] <= 2:
                raise FileNotFoundError("not yet")
            # Third call = post-replace check, pretend it's a symlink
            return symlink_stat
        return orig_lstat(path)

    unlinked = {"called": False}
    orig_unlink = os.unlink

    def fake_unlink(path):
        if str(path) == str(dest):
            unlinked["called"] = True
            return
        return orig_unlink(path)

    try:
        os.lstat = fake_lstat
        os.unlink = fake_unlink
        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {"name": "write_file", "input": {"path": str(dest), "content": "test"}},
        )
    finally:
        os.lstat = orig_lstat
        os.unlink = orig_unlink

    assert "TOCTOU" in res or "post-replace" in res or "symlink" in res


@pytest.mark.asyncio
async def test_write_file_s_islnk_raises(orchestrator, tmp_path):
    """If _stat.S_ISLNK raises on the post_stat check, we should continue (except pass)."""
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

    dest = tmp_path / "islnk_err.txt"
    dest.write_text("existing")

    # Make S_ISLNK raise on the destination's stat
    orig_S_ISLNK = _stat.S_ISLNK

    def bad_islnk(mode):
        raise RuntimeError("S_ISLNK exploded")

    try:
        _stat.S_ISLNK = bad_islnk
        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {
                "name": "write_file",
                "input": {"path": str(dest), "content": "new content"},
            },
        )
    finally:
        _stat.S_ISLNK = orig_S_ISLNK

    # Security sprint: any exception during path validation (including S_ISLNK)
    # is treated as a security denial to prevent bypassing symlink checks.
    assert "Security Error" in res or "denied" in res


# ---------------------------------------------------------------------------
# Write-file: TOCTOU identity change (st_ino/st_dev differ), covers os.unlink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_toctou_identity_change(orchestrator, tmp_path):
    """If inode changes between pre-write and post-write lstat, deny (TOCTOU)."""
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

    dest = tmp_path / "toctou_id.txt"
    dest.write_text("original")

    orig_lstat = os.lstat
    call_count = {"n": 0}

    def fake_lstat(path):
        if str(path) == str(dest):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                # is_symlink() check in _validate_path + pre-write lstat
                return SimpleNamespace(st_mode=0o100644, st_ino=1, st_dev=1)
            else:
                # post-write lstat: different inode -> TOCTOU
                return SimpleNamespace(st_mode=0o100644, st_ino=999, st_dev=1)
        return orig_lstat(path)

    try:
        os.lstat = fake_lstat
        res = await coord._execute_tool_for_sub_agent(
            "a1",
            {"name": "write_file", "input": {"path": str(dest), "content": "hacked"}},
        )
    finally:
        os.lstat = orig_lstat

    assert "TOCTOU" in res


# ---------------------------------------------------------------------------
# Gateway: _cleanup_rate_limits
# ---------------------------------------------------------------------------


def test_cleanup_rate_limits():
    """_cleanup_rate_limits removes client entries from all buckets."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
    )

    # Seed some rate limit entries
    gw.rate_limits["local"]["client_a"] = [datetime.now()]
    gw.rate_limits["local"]["client_b"] = [datetime.now()]
    gw.rate_limits["vpn"]["client_a"] = [datetime.now()]

    gw._cleanup_rate_limits("client_a")

    assert "client_a" not in gw.rate_limits["local"]
    assert "client_b" in gw.rate_limits["local"]
    assert "client_a" not in gw.rate_limits["vpn"]


def test_cleanup_rate_limits_nonexistent():
    """_cleanup_rate_limits on non-existent client does not raise."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
    )
    # Should not raise
    gw._cleanup_rate_limits("nonexistent_client")


# ---------------------------------------------------------------------------
# Gateway: health monitor rate-limit sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_monitor_sweeps_stale_rate_limits():
    """Health monitor loop should remove rate_limit entries for disconnected clients."""
    from core.network.gateway import UnifiedGateway

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
    )

    # Seed rate limits for a client that is NOT in gw.clients
    gw.rate_limits["local"]["stale_client"] = [datetime.now()]
    gw.rate_limits["local"]["active_client"] = [datetime.now()]

    # Mark one as active
    gw.clients["active_client"] = MagicMock()

    # Run health monitor for one iteration
    orig_sleep = asyncio.sleep

    async def one_iter_sleep(_):
        raise StopAsyncIteration("break loop")

    with patch("asyncio.sleep", side_effect=one_iter_sleep):
        with pytest.raises(StopAsyncIteration):
            await gw._health_monitor_loop()

    assert "stale_client" not in gw.rate_limits["local"]
    assert "active_client" in gw.rate_limits["local"]


# ---------------------------------------------------------------------------
# Gateway: _authenticate_connection edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_connection_timeout():
    """Auth timeout returns False."""
    from core.network.gateway import UnifiedGateway, ClientConnection, ConnectionType

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
        auth_token="secret123",
    )

    ws = MagicMock()
    aiter_mock = MagicMock()
    # Simulate timeout by raising asyncio.TimeoutError on __anext__
    anext_mock = AsyncMock(side_effect=asyncio.TimeoutError)
    aiter_mock.__anext__ = anext_mock
    ws.__aiter__ = MagicMock(return_value=aiter_mock)

    conn = ClientConnection(
        client_id="t1",
        websocket=ws,
        connection_type=ConnectionType.DIRECT,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    result = await gw._authenticate_connection(conn)
    assert result is False


@pytest.mark.asyncio
async def test_authenticate_connection_json_decode_error():
    """Non-JSON auth message returns False."""
    from core.network.gateway import UnifiedGateway, ClientConnection, ConnectionType

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
        auth_token="secret123",
    )

    ws = MagicMock()
    aiter_mock = MagicMock()
    # Return a non-JSON string
    anext_mock = AsyncMock(return_value="not json {{{")
    aiter_mock.__anext__ = anext_mock
    ws.__aiter__ = MagicMock(return_value=aiter_mock)

    conn = ClientConnection(
        client_id="t2",
        websocket=ws,
        connection_type=ConnectionType.DIRECT,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    result = await gw._authenticate_connection(conn)
    assert result is False


@pytest.mark.asyncio
async def test_authenticate_connection_stop_async_iteration():
    """StopAsyncIteration on ws read returns False."""
    from core.network.gateway import UnifiedGateway, ClientConnection, ConnectionType

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
        auth_token="secret123",
    )

    ws = MagicMock()
    aiter_mock = MagicMock()
    anext_mock = AsyncMock(side_effect=StopAsyncIteration)
    aiter_mock.__anext__ = anext_mock
    ws.__aiter__ = MagicMock(return_value=aiter_mock)

    conn = ClientConnection(
        client_id="t3",
        websocket=ws,
        connection_type=ConnectionType.DIRECT,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    result = await gw._authenticate_connection(conn)
    assert result is False


# ---------------------------------------------------------------------------
# Gateway: _handle_client cleanup on auth failure and disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_client_auth_failure_cleans_rate_limits():
    """When auth fails, rate_limits for the client should be cleaned."""
    from core.network.gateway import UnifiedGateway, ClientConnection, ConnectionType

    gw = UnifiedGateway(
        megabot_server_host="127.0.0.1",
        megabot_server_port=0,
        enable_cloudflare=False,
        enable_vpn=False,
        enable_direct_https=False,
        auth_token="secret123",
    )

    ws = MagicMock()
    aiter_mock = MagicMock()
    anext_mock = AsyncMock(return_value='{"type": "auth", "token": "wrong"}')
    aiter_mock.__anext__ = anext_mock
    ws.__aiter__ = MagicMock(return_value=aiter_mock)
    ws.send_str = AsyncMock()

    conn = ClientConnection(
        client_id="fail_client",
        websocket=ws,
        connection_type=ConnectionType.DIRECT,
        ip_address="127.0.0.1",
        connected_at=datetime.now(),
    )

    # Seed a rate limit entry
    gw.rate_limits["direct"]["fail_client"] = [datetime.now()]

    await gw._manage_connection(conn)

    # Rate limit should have been cleaned up
    assert "fail_client" not in gw.rate_limits.get("direct", {})


# ---------------------------------------------------------------------------
# AST validator edge cases
# ---------------------------------------------------------------------------


def test_ast_validator_blocks_dunder_attr():
    """AST validator blocks __class__ attribute access."""
    from features.dash_data.agent import _validate_ast
    import ast

    code = "x.__class__"
    tree = ast.parse(code, mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "__class__" in err


def test_ast_validator_blocks_unknown_dunder():
    """AST validator blocks unknown dunder attributes (belt-and-suspenders)."""
    from features.dash_data.agent import _validate_ast
    import ast

    code = "x.__totally_custom__"
    tree = ast.parse(code, mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "__totally_custom__" in err


def test_ast_validator_blocks_eval_call():
    """AST validator blocks eval() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("eval('1+1')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "eval" in err


def test_ast_validator_blocks_exec_call():
    """AST validator blocks exec() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("exec('pass')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "exec" in err


def test_ast_validator_blocks_open_call():
    """AST validator blocks open() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("open('/etc/passwd')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "open" in err


def test_ast_validator_blocks_getattr_call():
    """AST validator blocks getattr() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("getattr(x, 'secret')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "getattr" in err


def test_ast_validator_blocks_os_module_call():
    """AST validator blocks os.system() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("os.system('ls')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "os." in err


def test_ast_validator_blocks_subprocess_module_call():
    """AST validator blocks subprocess.run() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("subprocess.run(['ls'])", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "subprocess." in err


def test_ast_validator_blocks_import_from():
    """AST validator blocks 'from os import path'."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("from os import path", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "import" in err.lower()


def test_ast_validator_blocks_dunder_globals_name():
    """AST validator blocks __globals__ as a Name node."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("x = __globals__", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "__globals__" in err


def test_ast_validator_blocks_builtins_name():
    """AST validator blocks __builtins__ as a Name node."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("x = __builtins__", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "__builtins__" in err


def test_ast_validator_allows_safe_code():
    """AST validator allows simple arithmetic and list operations."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("x = [1, 2, 3]\ny = sum(x)\nz = len(x)", mode="exec")
    err = _validate_ast(tree)
    assert err is None


def test_ast_validator_blocks_compile():
    """AST validator blocks compile() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("compile('x', 'f', 'exec')", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "compile" in err


def test_ast_validator_blocks_type():
    """AST validator blocks type() calls."""
    from features.dash_data.agent import _validate_ast
    import ast

    tree = ast.parse("type(x)", mode="exec")
    err = _validate_ast(tree)
    assert err is not None
    assert "type" in err


# ---------------------------------------------------------------------------
# Orchestrator: _safe_ws_send edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_ws_send_none_ws(orchestrator):
    """_safe_ws_send returns False for None websocket."""
    from core.orchestrator import MegaBotOrchestrator

    orch = orchestrator
    result = await orch._safe_ws_send(None, {"type": "test"})
    assert result is False


@pytest.mark.asyncio
async def test_safe_ws_send_closed_ws(orchestrator):
    """_safe_ws_send returns False when ws.closed is True."""
    orch = orchestrator
    ws = MagicMock()
    ws.closed = True
    ws.close_code = None

    result = await orch._safe_ws_send(ws, {"type": "test"})
    assert result is False


@pytest.mark.asyncio
async def test_safe_ws_send_close_code_set(orchestrator):
    """_safe_ws_send returns False when close_code is an integer."""
    orch = orchestrator
    ws = MagicMock()
    ws.close_code = 1000  # Normal close

    result = await orch._safe_ws_send(ws, {"type": "test"})
    assert result is False


@pytest.mark.asyncio
async def test_safe_ws_send_send_raises(orchestrator):
    """_safe_ws_send returns False when send_json raises."""
    orch = orchestrator
    ws = MagicMock()
    ws.closed = False
    ws.close_code = None
    ws.send_json = AsyncMock(side_effect=ConnectionResetError("gone"))

    result = await orch._safe_ws_send(ws, {"type": "test"})
    assert result is False


@pytest.mark.asyncio
async def test_safe_ws_send_success(orchestrator):
    """_safe_ws_send returns True on successful send."""
    orch = orchestrator
    ws = MagicMock()
    ws.closed = False
    ws.close_code = None
    ws.send_json = AsyncMock()

    result = await orch._safe_ws_send(ws, {"type": "test"})
    assert result is True
    ws.send_json.assert_awaited_once_with({"type": "test"})
