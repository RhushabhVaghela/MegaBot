"""
Round 2 coverage tests for core/orchestrator.py
Target: lines 43-44, 237-239, 385, 472, 480-483, 510-511,
        736-739, 752-809, 1149-1173, 1628-1630, 1651-1652, 1673-1676
"""

import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from core.interfaces import Message


# ================================================================
# _safe_create_task _on_done callback (lines 43-44)
# ================================================================


@pytest.mark.asyncio
async def test_safe_create_task_on_done_non_cancelled_exception():
    """Lines 43-44: t.exception() raises non-CancelledError -> prints error."""
    from core.orchestrator import _safe_create_task

    async def failing_task():
        raise ValueError("something went wrong")

    task = _safe_create_task(failing_task(), name="test-fail")
    with pytest.raises(ValueError):
        await task


@pytest.mark.asyncio
async def test_safe_create_task_on_done_callback_error():
    """Lines 43-44: t.exception() itself raises a non-CancelledError."""
    from core.orchestrator import _safe_create_task, _orchestrator_tasks

    async def simple_task():
        return "done"

    task = _safe_create_task(simple_task(), name="test-ok")
    await task
    assert task not in _orchestrator_tasks


# ================================================================
# __init__ audit log attachment exception (lines 237-239)
# ================================================================


@pytest.mark.asyncio
async def test_init_audit_log_exception(mock_config):
    """Lines 237-239: exception in audit log setup -> pass (no crash)."""
    with patch(
        "core.orchestrator.attach_audit_file_handler",
        side_effect=RuntimeError("log fail"),
    ):
        with patch.dict("os.environ", {"MEGABOT_ENABLE_AUDIT_LOG": "1"}):
            from core.orchestrator import MegaBotOrchestrator

            orch = MegaBotOrchestrator(mock_config)
            assert orch is not None


# ================================================================
# run_autonomous_gateway_build memory injection (line 385)
# ================================================================


@pytest.mark.asyncio
async def test_gateway_build_memory_injection(orchestrator):
    """Line 385: lessons prepended to message.content."""
    gateway_mock = AsyncMock()
    gateway_mock.send_message = AsyncMock()
    orchestrator.adapters = {
        "mcp": AsyncMock(),
        "openclaw": AsyncMock(),
        "gateway": gateway_mock,
        "messaging": AsyncMock(),
    }
    orchestrator.adapters["mcp"].call_tool = AsyncMock(return_value="allowed_dirs")
    orchestrator.adapters["openclaw"].send_message = AsyncMock()
    orchestrator._get_relevant_lessons = AsyncMock(return_value="LESSON: do X")

    # Mock memory and message_handler for send_platform_message path
    orchestrator.memory.chat_write = AsyncMock()

    msg = Message(content="build something", sender="user", platform="gateway")
    original_data = {"_meta": {"client_id": "test-client", "connection_type": "local"}}

    await orchestrator.run_autonomous_gateway_build(msg, original_data)
    assert msg.content.startswith("LESSON: do X")


# ================================================================
# start() health wrapper - Mock detection (lines 472, 478-483)
# ================================================================


def _mock_all_adapters(orchestrator):
    """Replace all adapters with AsyncMocks so start() doesn't hit real services."""
    orchestrator.adapters = {
        "messaging": AsyncMock(),
        "gateway": AsyncMock(),
        "openclaw": AsyncMock(),
        "mcp": AsyncMock(),
    }
    orchestrator.discovery = MagicMock()
    orchestrator.rag = AsyncMock()
    orchestrator.background_tasks = AsyncMock()


@pytest.mark.asyncio
async def test_start_health_wrapper_mock_detection(orchestrator):
    """Lines 472, 478-479: Mock in cls_name -> return."""
    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=MagicMock())
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    # The health wrapper saw "MagicMock" in cls_name and returned early.
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_start_health_wrapper_last_resort_await(orchestrator):
    """Lines 480-483: non-Mock, non-coroutine -> last-resort await."""

    class AwaitableThing:
        """Not a coroutine/future/task, not a Mock."""

        def __await__(self):
            yield
            return None

    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = MagicMock(return_value=AwaitableThing())
    orchestrator.health_monitor = mock_monitor

    await orchestrator.start()
    await asyncio.sleep(0.05)
    await orchestrator.shutdown()


# ================================================================
# start() coro.close() raises (lines 510-511)
# ================================================================


@pytest.mark.asyncio
async def test_start_coro_close_raises(orchestrator):
    """Lines 510-511: coro.close() raises in finally -> pass."""
    _mock_all_adapters(orchestrator)

    mock_monitor = MagicMock()
    mock_monitor.start_monitoring = AsyncMock()
    orchestrator.health_monitor = mock_monitor

    with patch("asyncio.create_task", return_value="not-a-task"):
        with patch("asyncio.ensure_future", return_value="also-not"):
            await orchestrator.start()

    await orchestrator.shutdown()


# ================================================================
# _verify_redaction failure path (lines 736-739)
# ================================================================


@pytest.mark.asyncio
async def test_verify_redaction_failure(orchestrator):
    """Lines 736-739: remaining sensitive_regions -> return False."""
    orchestrator.computer_driver = AsyncMock()
    orchestrator.computer_driver.execute = AsyncMock(
        return_value=json.dumps(
            {"sensitive_regions": [{"x": 10, "y": 20, "w": 100, "h": 50}]}
        )
    )
    result = await orchestrator._verify_redaction("base64imagedata")
    assert result is False


@pytest.mark.asyncio
async def test_verify_redaction_success(orchestrator):
    """Lines 741-742: no remaining sensitive_regions -> return True."""
    orchestrator.computer_driver = AsyncMock()
    orchestrator.computer_driver.execute = AsyncMock(
        return_value=json.dumps({"sensitive_regions": []})
    )
    result = await orchestrator._verify_redaction("base64imagedata")
    assert result is True


# ================================================================
# _start_approval_escalation (lines 752-809)
# All tests below use the conftest orchestrator fixture.
# ================================================================


@pytest.mark.asyncio
async def test_escalation_action_not_in_queue(orchestrator):
    """Lines 752: action no longer in queue -> skip everything."""
    action = {"id": "action-xyz"}
    orchestrator.admin_handler.approval_queue = []

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_dnd_active_wrap_around(orchestrator):
    """Lines 757-770: DND active (dnd_start > dnd_end, e.g., 22-7)."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-1"}
    orchestrator.admin_handler.approval_queue = [action]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch("core.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=23)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_dnd_same_range(orchestrator):
    """Lines 765-766: DND with dnd_start <= dnd_end (e.g., 8-17)."""
    orchestrator.config.system.dnd_start = 8
    orchestrator.config.system.dnd_end = 17
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-2"}
    orchestrator.admin_handler.approval_queue = [action]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch("core.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=10)  # inside 8-17
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_calendar_dnd(orchestrator):
    """Lines 773-800: calendar event with DND keyword -> skip call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-3"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(
        return_value=[{"summary": "BUSY - Important Meeting"}]
    )
    orchestrator.adapters = {"mcp": mcp_mock, "messaging": MagicMock()}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch("core.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=15)  # outside DND
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await orchestrator._start_approval_escalation(action)


@pytest.mark.asyncio
async def test_escalation_calendar_check_fails(orchestrator):
    """Lines 797-800: calendar check raises exception -> continues to voice call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = "+1234567890"

    action = {"id": "action-4"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(side_effect=RuntimeError("calendar unavailable"))

    voice_mock = AsyncMock()
    voice_mock.make_call = AsyncMock()
    messaging_mock = MagicMock()
    messaging_mock.voice_adapter = voice_mock

    orchestrator.adapters = {"mcp": mcp_mock, "messaging": messaging_mock}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch("core.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=15)  # outside DND
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await orchestrator._start_approval_escalation(action)

    voice_mock.make_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_escalation_no_admin_phone(orchestrator):
    """Lines 808-809: no admin_phone -> prints message, no call."""
    orchestrator.config.system.dnd_start = 22
    orchestrator.config.system.dnd_end = 7
    orchestrator.config.system.admin_phone = None

    action = {"id": "action-5"}
    orchestrator.admin_handler.approval_queue = [action]

    mcp_mock = AsyncMock()
    mcp_mock.call_tool = AsyncMock(return_value=[])
    orchestrator.adapters = {"mcp": mcp_mock, "messaging": MagicMock()}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch("core.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=15)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await orchestrator._start_approval_escalation(action)


# ================================================================
# _handle_computer_tool (lines 1149-1173)
# ================================================================


@pytest.mark.asyncio
async def test_handle_computer_tool(orchestrator):
    """Lines 1149-1173: queues action, sends JSON, broadcasts."""
    ws_mock = AsyncMock()
    ws_mock.send_json = AsyncMock()

    client_mock = AsyncMock()
    client_mock.send_json = AsyncMock()
    orchestrator.clients = [client_mock]

    orchestrator.admin_handler = MagicMock()
    orchestrator.admin_handler.approval_queue = []

    tool_input = {"action": "screenshot", "x": 100, "y": 200}
    await orchestrator._handle_computer_tool(tool_input, ws_mock, action_id="act-123")

    assert len(orchestrator.admin_handler.approval_queue) == 1
    queued = orchestrator.admin_handler.approval_queue[0]
    assert queued["id"] == "act-123"
    assert queued["type"] == "computer_use"

    ws_mock.send_json.assert_awaited_once()
    call_args = ws_mock.send_json.call_args[0][0]
    assert call_args["type"] == "status"

    client_mock.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_computer_tool_auto_id(orchestrator):
    """Lines 1156: action_id is None -> auto-generate UUID."""
    ws_mock = AsyncMock()
    ws_mock.send_json = AsyncMock()
    orchestrator.clients = []
    orchestrator.admin_handler = MagicMock()
    orchestrator.admin_handler.approval_queue = []

    tool_input = {"action": "click"}
    await orchestrator._handle_computer_tool(tool_input, ws_mock, action_id=None)

    queued = orchestrator.admin_handler.approval_queue[0]
    assert queued["id"]  # Should have auto-generated UUID


# ================================================================
# shutdown() - health_monitor.stop() raises (lines 1628-1630)
# ================================================================


@pytest.mark.asyncio
async def test_shutdown_health_monitor_stop_raises(orchestrator):
    """Lines 1628-1630: health_monitor.stop() raises -> pass."""
    mock_monitor = MagicMock()
    mock_monitor.stop = MagicMock(side_effect=RuntimeError("stop failed"))
    orchestrator.health_monitor = mock_monitor
    orchestrator._health_task = None

    await orchestrator.shutdown()


# ================================================================
# shutdown() - background_tasks.shutdown() raises (lines 1651-1652)
# ================================================================


@pytest.mark.asyncio
async def test_shutdown_background_tasks_await_exception(orchestrator):
    """Lines 1651-1652: await background_tasks.shutdown() raises -> pass."""

    async def failing_shutdown():
        raise RuntimeError("shutdown boom")

    mock_bg = MagicMock()
    mock_bg.shutdown = MagicMock(return_value=failing_shutdown())
    orchestrator.background_tasks = mock_bg
    orchestrator.health_monitor = None
    orchestrator._health_task = MagicMock()
    orchestrator._health_task.cancel = MagicMock()
    orchestrator._health_task.__class__ = type("MagicMock", (), {})

    await orchestrator.shutdown()


# ================================================================
# shutdown() - __await__.__self__ coroutine close (lines 1673-1676)
# ================================================================


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close(orchestrator):
    """Lines 1673-1676: __await__.__self__ is a coroutine -> close it."""

    async def dummy():
        pass

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    mock_task.__await__ = coro.__await__
    mock_task.__class__ = type("MagicMock", (), {})

    orchestrator._health_task = mock_task
    orchestrator.health_monitor = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)

    await orchestrator.shutdown()

    try:
        coro.close()
    except RuntimeError:
        pass


@pytest.mark.asyncio
async def test_shutdown_health_task_coro_close_raises(orchestrator):
    """Lines 1673-1674: possible_coro.close() raises -> pass."""

    async def dummy():
        pass

    coro = dummy()

    mock_task = MagicMock()
    mock_task.cancel = MagicMock()

    await_fn = MagicMock()
    await_fn.__self__ = coro
    mock_task.__await__ = await_fn
    mock_task.__class__ = type("MagicMock", (), {})

    orchestrator._health_task = mock_task
    orchestrator.health_monitor = None
    orchestrator.background_tasks = MagicMock()
    orchestrator.background_tasks.shutdown = MagicMock(return_value=None)

    await orchestrator.shutdown()

    try:
        coro.close()
    except RuntimeError:
        pass
