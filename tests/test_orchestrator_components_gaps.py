"""
Tests for uncovered lines in core/orchestrator_components.py.

Targets:
  - HealthMonitor.shutdown() (lines 157-179)
  - BackgroundTasks._safe_schedule ensure_future fallback (lines 282-283)
  - BackgroundTasks._safe_schedule coro.close() on total failure (lines 287-294)
  - BackgroundTasks.start_all_tasks coroutine creation raises (lines 304-306)
  - BackgroundTasks.start_all_tasks skip None coro (line 308-310)
  - BackgroundTasks.start_all_tasks close coro when _safe_schedule returns None (lines 316-323)
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from core.orchestrator_components import HealthMonitor, BackgroundTasks


@pytest.fixture
def mock_orch():
    orch = MagicMock()
    orch.memory = AsyncMock()
    orch.adapters = {
        "openclaw": AsyncMock(),
        "messaging": MagicMock(clients=[]),
        "mcp": AsyncMock(servers=[]),
        "memu": AsyncMock(),
    }
    orch.send_platform_message = AsyncMock()
    orch.restart_component = AsyncMock()
    return orch


# ---------- HealthMonitor.shutdown() ----------


class TestHealthMonitorShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_awaits_and_clears(self, mock_orch):
        """shutdown() cancels all tasks, awaits them, and clears state."""
        monitor = HealthMonitor(mock_orch)

        # Use mock tasks that pass isinstance checks and are awaitable.
        # Real cancelled tasks raise CancelledError (BaseException) which
        # the source code's `except Exception` doesn't catch, so use mocks.
        t1 = AsyncMock(spec=asyncio.Task)
        t1.cancel = MagicMock()
        t2 = AsyncMock(spec=asyncio.Task)
        t2.cancel = MagicMock()

        monitor._tasks = [t1, t2]
        monitor.last_status = {"memory": {"status": "up"}}
        monitor.restart_counts = {"memory": 1}

        await monitor.shutdown()

        t1.cancel.assert_called_once()
        t2.cancel.assert_called_once()
        assert monitor._tasks == []
        assert monitor.last_status == {}
        assert monitor.restart_counts == {}

    @pytest.mark.asyncio
    async def test_shutdown_handles_cancel_exception(self, mock_orch):
        """shutdown() doesn't raise when task.cancel() itself throws."""
        monitor = HealthMonitor(mock_orch)

        bad_task = MagicMock()
        bad_task.cancel.side_effect = RuntimeError("cancel failed")
        monitor._tasks = [bad_task]
        monitor.last_status = {"x": "y"}
        monitor.restart_counts = {"x": 1}

        await monitor.shutdown()

        assert monitor._tasks == []
        assert monitor.last_status == {}

    @pytest.mark.asyncio
    async def test_shutdown_await_raises_regular_exception(self, mock_orch):
        """shutdown() handles regular Exception from awaiting a task gracefully."""
        monitor = HealthMonitor(mock_orch)

        # Create an awaitable mock that raises a regular Exception when awaited
        t = AsyncMock(spec=asyncio.Task)
        t.cancel = MagicMock()
        t.__await__ = MagicMock(side_effect=RuntimeError("await boom"))

        # For isinstance(t, asyncio.Task) to pass, spec=asyncio.Task is set.
        # But `await t` invokes __await__. AsyncMock handles this differently.
        # Let's use a custom awaitable class instead.
        class FailingTask:
            """A task-like object that raises when awaited."""

            def cancel(self):
                pass

            def __await__(self):
                raise RuntimeError("boom")
                yield  # noqa: F841 - makes it a generator

        ft = FailingTask()
        monitor._tasks = [ft]

        # isinstance(ft, asyncio.Task) is False, asyncio.isfuture(ft) is False,
        # so the await branch is skipped. We need to test the inner except.
        # Let's use a real task approach with a task that raises a regular error.
        async def _raise():
            raise RuntimeError("task error")

        real_task = asyncio.create_task(_raise())
        # Let the task run and fail
        await asyncio.sleep(0)
        monitor._tasks = [real_task]

        # The task already completed with an exception.
        # `await real_task` re-raises RuntimeError which is caught by except Exception.
        await monitor.shutdown()
        assert monitor._tasks == []

    @pytest.mark.asyncio
    async def test_shutdown_isinstance_check_raises(self, mock_orch):
        """shutdown() handles mocked types that raise on isinstance checks."""
        monitor = HealthMonitor(mock_orch)

        # The outer except (line 173) catches errors from isinstance/isfuture.
        # We can trigger this by making asyncio.isfuture raise.
        class WeirdObj:
            def cancel(self):
                pass

        obj = WeirdObj()
        monitor._tasks = [obj]

        with patch("asyncio.isfuture", side_effect=TypeError("weird type")):
            await monitor.shutdown()

        assert monitor._tasks == []


# ---------- BackgroundTasks._safe_schedule & start_all_tasks ----------


def _make_fake_coro():
    """Return a mock object that looks like a coroutine (has .close())."""
    fake = MagicMock()
    fake.close = MagicMock()
    return fake


class TestBackgroundTasksScheduling:
    @pytest.mark.asyncio
    async def test_safe_schedule_ensure_future_fallback(self, mock_orch):
        """When create_task fails, _safe_schedule falls back to ensure_future."""
        tasks = BackgroundTasks(mock_orch)

        fake_coro = _make_fake_coro()
        mock_task = MagicMock()

        # Use MagicMock(return_value=...) for loop stubs to avoid AsyncMock
        # returning coroutines when we want None/specific values.
        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch(
                            "asyncio.create_task",
                            side_effect=RuntimeError("no loop"),
                        ):
                            with patch(
                                "asyncio.ensure_future",
                                return_value=mock_task,
                            ) as ef_mock:
                                await tasks.start_all_tasks()
                                ef_mock.assert_called_once_with(fake_coro)
                                assert mock_task in tasks._tasks

    @pytest.mark.asyncio
    async def test_safe_schedule_both_fail_closes_coro(self, mock_orch):
        """When both create_task and ensure_future fail, coro.close() is called."""
        tasks = BackgroundTasks(mock_orch)

        fake_coro = _make_fake_coro()

        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch(
                            "asyncio.create_task",
                            side_effect=RuntimeError("boom"),
                        ):
                            with patch(
                                "asyncio.ensure_future",
                                side_effect=RuntimeError("boom2"),
                            ):
                                await tasks.start_all_tasks()

        # close() should have been called at least once (inside _safe_schedule)
        # and potentially again in the outer loop safety net
        assert fake_coro.close.call_count >= 1
        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_coroutine_creation_raises(self, mock_orch):
        """When calling a loop function raises, start_all_tasks skips it."""
        tasks = BackgroundTasks(mock_orch)

        with patch.object(
            tasks, "sync_loop", new=MagicMock(side_effect=RuntimeError("coro boom"))
        ):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        # Should not raise
                        await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_skip_none_coro(self, mock_orch):
        """When a loop function returns None, start_all_tasks skips scheduling."""
        tasks = BackgroundTasks(mock_orch)

        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=None)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch("asyncio.create_task") as ct:
                            await tasks.start_all_tasks()
                            ct.assert_not_called()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_all_tasks_outer_close_on_schedule_failure(self, mock_orch):
        """When _safe_schedule returns None, the outer code closes the coro too."""
        tasks = BackgroundTasks(mock_orch)

        fake_coro = _make_fake_coro()

        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch(
                            "asyncio.create_task",
                            side_effect=RuntimeError("no"),
                        ):
                            with patch(
                                "asyncio.ensure_future",
                                side_effect=RuntimeError("no"),
                            ):
                                await tasks.start_all_tasks()

        # close() called inside _safe_schedule (line 291) AND in the
        # outer loop (line 320) = at least 2 calls
        assert fake_coro.close.call_count >= 2
        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_safe_schedule_coro_close_raises(self, mock_orch):
        """When coro.close() raises inside _safe_schedule, except catches it (lines 292-293)."""
        tasks = BackgroundTasks(mock_orch)

        fake_coro = MagicMock()
        fake_coro.close = MagicMock(side_effect=RuntimeError("close boom"))

        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch(
                            "asyncio.create_task",
                            side_effect=RuntimeError("no"),
                        ):
                            with patch(
                                "asyncio.ensure_future",
                                side_effect=RuntimeError("no"),
                            ):
                                # Should not raise even though close() throws
                                await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0

    @pytest.mark.asyncio
    async def test_outer_loop_coro_close_raises(self, mock_orch):
        """When coro.close() raises in the outer loop, except catches it (lines 322-323)."""
        tasks = BackgroundTasks(mock_orch)

        # We need close() to succeed inside _safe_schedule (so _safe_schedule
        # returns None normally) but fail in the outer loop.
        call_count = [0]

        def close_sometimes():
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("close boom in outer")

        fake_coro = MagicMock()
        fake_coro.close = MagicMock(side_effect=close_sometimes)

        with patch.object(tasks, "sync_loop", new=MagicMock(return_value=fake_coro)):
            with patch.object(
                tasks, "proactive_loop", new=MagicMock(return_value=None)
            ):
                with patch.object(
                    tasks, "pruning_loop", new=MagicMock(return_value=None)
                ):
                    with patch.object(
                        tasks, "backup_loop", new=MagicMock(return_value=None)
                    ):
                        with patch(
                            "asyncio.create_task",
                            side_effect=RuntimeError("no"),
                        ):
                            with patch(
                                "asyncio.ensure_future",
                                side_effect=RuntimeError("no"),
                            ):
                                await tasks.start_all_tasks()

        assert len(tasks._tasks) == 0
