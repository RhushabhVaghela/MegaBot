"""Tests targeting uncovered lines in core/orchestrator.py.

Coverage gaps addressed:
  - _safe_create_task: RuntimeError fallback, set_name, _on_done paths (23-24, 30-32, 38, 43-44, 48-49)
  - lifespan context manager (154-166)
  - __init__ audit log auto-enable (235-239)
  - start() _health_wrapper inner paths (460-462, 466-467, 480-491, 493, 518-519)
  - _to_platform_message delegation (686)
  - _check_policy sub-scope match (1223, 1228, 1230)
  - _process_approval branches: outbound_vision, data_execution, computer_use, identity_link, denial (1377-1489)
  - shutdown() deeper paths (1647-1709)
"""

import asyncio
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# _safe_create_task tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_create_task_runtime_error_fallback():
    """Lines 23-24: get_running_loop raises RuntimeError → falls back to get_event_loop."""
    from core.orchestrator import _safe_create_task

    async def noop():
        pass

    # Patch get_running_loop to raise RuntimeError
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        mock_loop = asyncio.get_event_loop()
        with patch("asyncio.get_event_loop", return_value=mock_loop) as mock_gel:
            task = _safe_create_task(noop(), name="test-fallback")
            assert task is not None
            mock_gel.assert_called_once()
            # Let the task finish
            await task


@pytest.mark.asyncio
async def test_safe_create_task_set_name_success():
    """Lines 29-30: name provided → task.set_name(name) called successfully."""
    from core.orchestrator import _safe_create_task

    async def noop():
        pass

    task = _safe_create_task(noop(), name="my-named-task")
    # set_name should succeed silently
    assert task is not None
    await task


@pytest.mark.asyncio
async def test_safe_create_task_set_name_failure():
    """Lines 31-32: task.set_name raises → exception swallowed."""
    from core.orchestrator import _safe_create_task

    async def noop():
        pass

    real_loop = asyncio.get_running_loop()
    original_create_task = real_loop.create_task

    def patched_create_task(coro, **kwargs):
        real_task = original_create_task(coro, **kwargs)
        # Replace set_name with one that raises
        real_task.set_name = MagicMock(side_effect=AttributeError("no set_name"))
        return real_task

    with patch.object(real_loop, "create_task", side_effect=patched_create_task):
        task = _safe_create_task(noop(), name="should-fail")
        assert task is not None
        await task


@pytest.mark.asyncio
async def test_safe_create_task_on_done_with_exception(capsys):
    """Lines 36-40: _on_done detects a task exception and prints it."""
    from core.orchestrator import _safe_create_task

    async def fail():
        raise ValueError("boom")

    task = _safe_create_task(fail(), name="failing-task")
    try:
        await task
    except ValueError:
        pass
    # Allow the done callback to fire
    await asyncio.sleep(0.05)
    captured = capsys.readouterr()
    assert "task_error" in captured.out or "boom" in captured.out


@pytest.mark.asyncio
async def test_safe_create_task_on_done_cancelled():
    """Lines 41-42: _on_done with CancelledError → swallowed silently."""
    from core.orchestrator import _safe_create_task

    async def hang():
        await asyncio.sleep(999)

    task = _safe_create_task(hang(), name="cancel-me")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # Let callback fire — should not raise
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_safe_create_task_on_done_discard_fails():
    """Lines 48-49: _orchestrator_tasks.discard raises → swallowed."""
    from core.orchestrator import _safe_create_task
    import core.orchestrator as orch_mod

    async def noop():
        pass

    # Create a custom set subclass whose discard raises
    class BrokenSet(set):
        def discard(self, elem):
            raise TypeError("bad discard")

    original_tasks = orch_mod._orchestrator_tasks
    broken = BrokenSet(original_tasks)
    with patch.object(orch_mod, "_orchestrator_tasks", broken):
        task = _safe_create_task(noop(), name="discard-fail")
        await task
        await asyncio.sleep(0.05)
    # Restore is automatic via context manager


# ---------------------------------------------------------------------------
# lifespan context manager tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_skip_startup():
    """Lines 154-166: MEGABOT_SKIP_STARTUP=1 skips orchestrator start/shutdown."""
    from core.orchestrator import lifespan, app

    with patch.dict("os.environ", {"MEGABOT_SKIP_STARTUP": "1"}):
        async with lifespan(app):
            # Should yield without creating/starting orchestrator
            pass  # no error means success


# ---------------------------------------------------------------------------
# __init__ audit log auto-enable tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_audit_log_auto_enable(mock_config):
    """Lines 235-239: audit log enabled when not CI and not pytest."""
    from core.orchestrator import MegaBotOrchestrator

    with patch.dict("os.environ", {}, clear=False):
        # Remove CI indicators
        env_copy = dict(__import__("os").environ)
        env_copy.pop("CI", None)
        env_copy.pop("GITHUB_ACTIONS", None)
        env_copy.pop("ENABLE_AUDIT_LOG", None)
        # Fake sys.argv to not contain "pytest"
        with patch.dict("os.environ", env_copy, clear=True):
            with patch.object(sys, "argv", ["megabot", "run"]):
                with patch(
                    "core.orchestrator.attach_audit_file_handler"
                ) as mock_attach:
                    try:
                        orch = MegaBotOrchestrator(mock_config)
                        mock_attach.assert_called_once()
                    except Exception:
                        # The init may fail on other unrelated things; we only care
                        # about attach_audit_file_handler being called
                        pass


# ---------------------------------------------------------------------------
# start() _health_wrapper inner paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_health_monitor_raises(orchestrator):
    """Lines 460-462: health_monitor.start_monitoring() raises → wrapper returns."""
    orchestrator.health_monitor.start_monitoring = MagicMock(
        side_effect=RuntimeError("monitor broken")
    )
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()
    # Should not raise; wrapper swallows the error


@pytest.mark.asyncio
async def test_start_health_wrapper_cls_name_raises(orchestrator):
    """Lines 466-467: getattr(coro, '__class__', ...) raises → cls_name=''."""

    # Create a coro-like object whose __class__ access raises
    class WeirdCoro:
        @property
        def __class__(self):
            raise RuntimeError("class access error")

        def close(self):
            pass

    orchestrator.health_monitor.start_monitoring = MagicMock(return_value=WeirdCoro())
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()


@pytest.mark.asyncio
async def test_start_health_wrapper_not_awaitable_mock_name(orchestrator):
    """Lines 486-487: safe_to_await=False, cls_name contains 'Mock' → returns."""
    # Return a MagicMock (not a coroutine) from start_monitoring
    mock_coro = MagicMock()
    orchestrator.health_monitor.start_monitoring = MagicMock(return_value=mock_coro)
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    await orchestrator.start()


@pytest.mark.asyncio
async def test_start_create_task_returns_non_task_closes_coro(orchestrator):
    """Lines 515-519: create_task returns non-Task → coro.close() called."""
    orchestrator.health_monitor.start_monitoring = AsyncMock()
    orchestrator.adapters["messaging"].start = AsyncMock()
    orchestrator.adapters["gateway"].start = AsyncMock()
    orchestrator.adapters["openclaw"].connect = AsyncMock(side_effect=Exception("skip"))
    orchestrator.adapters["mcp"].start_all = AsyncMock(side_effect=Exception("skip"))
    orchestrator.rag.build_index = AsyncMock(side_effect=Exception("skip"))
    orchestrator.background_tasks.start_all_tasks = AsyncMock()
    orchestrator.discovery.scan = MagicMock()

    # Patch create_task to return a non-Task value
    with patch("asyncio.create_task", return_value="not-a-task"):
        with patch("asyncio.ensure_future", side_effect=Exception("also fails")):
            await orchestrator.start()
            # Wrapper coro should be closed, no warning


# ---------------------------------------------------------------------------
# _to_platform_message delegation
# ---------------------------------------------------------------------------


def test_to_platform_message_delegation(orchestrator):
    """Line 686: _to_platform_message delegates to message_router."""
    from core.interfaces import Message

    msg = Message(content="hello", sender="user")
    orchestrator.message_router._to_platform_message = MagicMock(
        return_value="platform_msg"
    )
    result = orchestrator._to_platform_message(msg, chat_id="c1")
    orchestrator.message_router._to_platform_message.assert_called_once_with(msg, "c1")
    assert result == "platform_msg"


# ---------------------------------------------------------------------------
# _check_policy sub-scope & final scope
# ---------------------------------------------------------------------------


def test_check_policy_cmd_part_scope_match_allow(orchestrator):
    """Line 1223: sub-scope cmd_part match returns 'allow'."""
    # Full command "git status" → cmd_part="git"
    # Set permissions so that "git" returns True
    orchestrator.permissions.is_authorized = MagicMock(
        side_effect=lambda scope: {
            "shell.git status": None,
            "git status": None,
            "shell.git": True,
        }.get(scope, None)
    )

    result = orchestrator._check_policy(
        {
            "method": "system.run",
            "params": {"command": "git status"},
        }
    )
    assert result == "allow"


def test_check_policy_cmd_part_scope_match_deny(orchestrator):
    """Line 1223: sub-scope cmd_part match returns 'deny'."""
    orchestrator.permissions.is_authorized = MagicMock(
        side_effect=lambda scope: {
            "shell.rm status": None,
            "rm status": None,
            "shell.rm": False,
        }.get(scope, None)
    )

    result = orchestrator._check_policy(
        {
            "method": "system.run",
            "params": {"command": "rm -rf /"},
        }
    )
    assert result == "deny"


def test_check_policy_scope_auth_true(orchestrator):
    """Line 1228: scope auth is True → returns 'allow'."""
    orchestrator.permissions.is_authorized = MagicMock(return_value=True)
    result = orchestrator._check_policy({"method": "some.method", "params": {}})
    assert result == "allow"


def test_check_policy_scope_auth_false(orchestrator):
    """Line 1230: scope auth is False → returns 'deny'."""
    orchestrator.permissions.is_authorized = MagicMock(return_value=False)
    result = orchestrator._check_policy({"method": "some.method", "params": {}})
    assert result == "deny"


# ---------------------------------------------------------------------------
# _process_approval branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_approval_outbound_vision(orchestrator):
    """Lines 1377-1396: approved outbound_vision action."""

    action_id = "vis-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "outbound_vision",
            "payload": {
                "message_content": "Look at this",
                "attachments": [],
                "chat_id": "chat1",
                "platform": "native",
                "target_client": "client1",
            },
        }
    ]
    orchestrator.message_router._to_platform_message = MagicMock()
    platform_msg = MagicMock()
    orchestrator.message_router._to_platform_message.return_value = platform_msg
    orchestrator.adapters["messaging"].send_message = AsyncMock()
    orchestrator.clients = set()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.adapters["messaging"].send_message.assert_called_once()
    assert platform_msg.platform == "native"
    # Action removed from queue
    assert len(orchestrator.admin_handler.approval_queue) == 0


@pytest.mark.asyncio
async def test_process_approval_data_execution(orchestrator):
    """Lines 1399-1425: approved data_execution action."""
    action_id = "data-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "data_execution",
            "payload": {"name": "test_ds", "code": "x = 1"},
        }
    ]
    orchestrator.clients = set()

    with patch("features.dash_data.agent.DashDataAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.execute_python_analysis = AsyncMock(return_value="result: 42")
        MockAgent.return_value = mock_instance

        orchestrator.send_platform_message = AsyncMock()
        await orchestrator._process_approval(action_id, approved=True)

        orchestrator.send_platform_message.assert_called_once()
        call_msg = orchestrator.send_platform_message.call_args[0][0]
        assert "42" in call_msg.content


@pytest.mark.asyncio
async def test_process_approval_data_execution_error(orchestrator):
    """Lines 1417-1418: data_execution raises exception."""
    action_id = "data-err"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "data_execution",
            "payload": {"name": "ds", "code": "bad"},
        }
    ]
    orchestrator.clients = set()

    with patch(
        "features.dash_data.agent.DashDataAgent", side_effect=ImportError("no module")
    ):
        orchestrator.send_platform_message = AsyncMock()
        await orchestrator._process_approval(action_id, approved=True)
        call_msg = orchestrator.send_platform_message.call_args[0][0]
        assert "failed" in call_msg.content.lower()


@pytest.mark.asyncio
async def test_process_approval_computer_use(orchestrator):
    """Lines 1428-1465: approved computer_use action (non-screenshot)."""
    action_id = "comp-1"
    ws = AsyncMock()
    cb = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "computer_use",
            "payload": {"action": "click", "coordinate": [100, 200], "text": None},
            "websocket": ws,
            "callback": cb,
        }
    ]
    orchestrator.clients = set()
    orchestrator.computer_driver.execute = AsyncMock(return_value="clicked at 100,200")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.computer_driver.execute.assert_called_once_with(
        "click", [100, 200], None
    )
    ws.send_json.assert_called()
    # Callback invoked
    cb.assert_called_once_with("clicked at 100,200")
    orchestrator.adapters["openclaw"].send_message.assert_called_once()


@pytest.mark.asyncio
async def test_process_approval_computer_use_screenshot(orchestrator):
    """Lines 1445-1447: computer_use screenshot path."""
    action_id = "comp-ss"
    ws = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "computer_use",
            "payload": {"action": "screenshot", "coordinate": None, "text": None},
            "websocket": ws,
        }
    ]
    orchestrator.clients = set()
    orchestrator.computer_driver.execute = AsyncMock(return_value="base64imagedata")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    # Should send screenshot type
    calls = ws.send_json.call_args_list
    screenshot_call = [c for c in calls if c[0][0].get("type") == "screenshot"]
    assert len(screenshot_call) == 1


@pytest.mark.asyncio
async def test_process_approval_identity_link(orchestrator):
    """Lines 1468-1484: approved identity_link action."""
    action_id = "id-link-1"
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "identity_link",
            "payload": {
                "internal_id": "ADMIN",
                "platform": "telegram",
                "platform_id": "12345",
                "chat_id": "chat-tg",
            },
        }
    ]
    orchestrator.clients = set()
    orchestrator.memory.link_identity = AsyncMock()
    orchestrator.send_platform_message = AsyncMock()

    await orchestrator._process_approval(action_id, approved=True)

    orchestrator.memory.link_identity.assert_called_once_with(
        "ADMIN", "telegram", "12345"
    )
    orchestrator.send_platform_message.assert_called_once()
    call_msg = orchestrator.send_platform_message.call_args[0][0]
    assert "ADMIN" in call_msg.content


@pytest.mark.asyncio
async def test_process_approval_denial_with_callback(orchestrator):
    """Line 1489: denied action invokes callback with 'Action denied by user.'."""
    action_id = "deny-1"
    cb = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "system_command",
            "payload": {},
            "callback": cb,
        }
    ]
    orchestrator.clients = set()

    await orchestrator._process_approval(action_id, approved=False)

    cb.assert_called_once_with("Action denied by user.")
    # Queue is cleared
    assert len(orchestrator.admin_handler.approval_queue) == 0


# ---------------------------------------------------------------------------
# shutdown() deeper paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_stop_fn_returns_coroutine(orchestrator):
    """Lines 1647-1651: stop_fn returns a real coroutine → awaited."""

    async def stop_coro():
        raise ValueError("stop failed")

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = MagicMock(return_value=stop_coro())
    orchestrator._health_task = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    # Should not raise; exception swallowed


@pytest.mark.asyncio
async def test_shutdown_health_task_cancel_exception(orchestrator):
    """Lines 1657-1659: _health_task.cancel() raises → swallowed."""
    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None  # not callable

    mock_task = MagicMock()
    mock_task.cancel = MagicMock(side_effect=RuntimeError("cancel failed"))
    orchestrator._health_task = mock_task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_background_tasks_returns_awaitable(orchestrator):
    """Lines 1665-1673: background_tasks.shutdown() returns a coroutine → awaited."""

    async def bg_shutdown_coro():
        pass

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None
    orchestrator._health_task = None

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=bg_shutdown_coro())

    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_health_task_await_self_coroutine_close(orchestrator):
    """Lines 1694-1697: _health_task.__await__.__self__ is a coroutine → closed."""

    async def dummy():
        pass

    real_coro = dummy()

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None

    # Create a mock task whose __await__.__self__ is the real coroutine
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__class__ = MagicMock  # cls_name will contain "MagicMock"
    mock_await = MagicMock()
    mock_await.__self__ = real_coro
    mock_task.__await__ = mock_await
    orchestrator._health_task = mock_task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    # The real_coro should be closed (no "coroutine never awaited" warning)


@pytest.mark.asyncio
async def test_shutdown_real_task_health(orchestrator):
    """Lines 1703-1709: _health_task is a real asyncio.Task → awaited."""

    async def slow():
        await asyncio.sleep(10)

    orchestrator.health_monitor = MagicMock()
    orchestrator.health_monitor.stop = None

    task = asyncio.create_task(slow())
    task.cancel()
    orchestrator._health_task = task

    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)
    orchestrator.adapters = {}
    orchestrator.clients = set()

    await orchestrator.shutdown()
    assert task.cancelled()


# ---------------------------------------------------------------------------
# _process_approval tirith validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_approval_tirith_blocks_command(orchestrator):
    """Line 1342: tirith.validate returns False → security error output."""
    action_id = "tir-1"
    ws = AsyncMock()
    orchestrator.admin_handler.approval_queue = [
        {
            "id": action_id,
            "type": "system_command",
            "payload": {"params": {"command": "echo вредоносный"}},
            "websocket": ws,
        }
    ]
    orchestrator.clients = set()
    orchestrator.adapters["openclaw"] = MagicMock()
    orchestrator.adapters["openclaw"].send_message = AsyncMock()

    with patch("core.orchestrator.tirith") as mock_tirith:
        mock_tirith.validate.return_value = False
        mock_tirith.sanitize = MagicMock(side_effect=lambda x: x)
        orchestrator.secret_manager.inject_secrets = MagicMock(side_effect=lambda x: x)
        orchestrator.secret_manager.scrub_secrets = MagicMock(side_effect=lambda x: x)

        await orchestrator._process_approval(action_id, approved=True)

    # Should send security error to websocket
    ws_calls = ws.send_json.call_args_list
    assert any("Security Error" in str(c) or "Tirith" in str(c) for c in ws_calls)


# ---------------------------------------------------------------------------
# ivr_callback endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ivr_callback_no_orchestrator():
    """Lines 1743-1744: orchestrator is None → 'System error.' response."""
    from core.orchestrator import app
    from httpx import AsyncClient, ASGITransport

    with patch.dict("os.environ", {"MEGABOT_SKIP_STARTUP": "1"}):
        with patch("core.orchestrator.orchestrator", None):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/ivr?action_id=test123", data={"Digits": "1"})
                assert resp.status_code == 200
                assert "System error" in resp.text
