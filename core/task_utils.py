"""
Safe async task scheduling utilities for MegaBot.

Provides a wrapper around ``asyncio.create_task`` that:
- Tracks all outstanding tasks so they can be awaited on shutdown.
- Logs unhandled exceptions instead of silently dropping them.

Import ``safe_create_task`` from this module instead of using
``asyncio.create_task`` directly throughout the codebase.
"""

import asyncio
import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)

# Global set of all tracked tasks — prevents GC while running.
_tracked_tasks: Set[asyncio.Task] = set()


def safe_create_task(coro, name: Optional[str] = None) -> asyncio.Task:
    """Schedule *coro* as an asyncio Task with error logging.

    The task is added to ``_tracked_tasks`` and removed automatically
    when it completes.  Any unhandled exception is logged rather than
    silently swallowed.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    task = loop.create_task(coro)
    try:
        if name:
            task.set_name(name)
    except Exception:
        pass

    def _on_done(t: asyncio.Task):
        try:
            exc = t.exception()
            if exc:
                task_name = getattr(t, "get_name", lambda: repr(t))()
                logger.error("[task_error] %s: %s", task_name, exc, exc_info=exc)
        except asyncio.CancelledError:
            pass
        except Exception as cb_err:
            logger.error("[task_callback_error] %s", cb_err)
        finally:
            _tracked_tasks.discard(t)

    _tracked_tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def get_tracked_tasks() -> Set[asyncio.Task]:
    """Return a snapshot of all currently tracked tasks."""
    return set(_tracked_tasks)


# ---- JSON-safe helpers for approval queue broadcasts ----
# Action dicts may carry non-serializable objects (WebSocket, callables)
# that are needed internally but must be stripped before ``send_json``.
_NON_SERIALIZABLE_KEYS = frozenset({"websocket", "callback"})


def sanitize_action(action: dict) -> dict:
    """Return a shallow copy of *action* without non-serializable fields."""
    return {k: v for k, v in action.items() if k not in _NON_SERIALIZABLE_KEYS}


def sanitize_queue(queue: list) -> list:
    """Return a JSON-safe copy of the entire approval queue."""
    return [sanitize_action(a) for a in queue]
