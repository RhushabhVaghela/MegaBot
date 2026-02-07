"""Orchestrator lifecycle management: start, shutdown, restart, health monitoring.

Extracted from ``core/orchestrator.py`` to isolate process lifecycle
concerns from business orchestration logic.
"""

import asyncio
from typing import Any, Dict, TYPE_CHECKING

from core.interfaces import Message
from core.task_utils import safe_create_task as _safe_create_task

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator


async def start(orchestrator: "MegaBotOrchestrator") -> None:
    """Start the orchestrator: connect adapters, build indexes, launch background tasks.

    Args:
        orchestrator: The MegaBotOrchestrator instance to start.
    """
    print(f"Starting {orchestrator.config.system.name} in {orchestrator.mode} mode...")
    # PERF-11: avoid blocking the event loop with synchronous I/O
    await asyncio.to_thread(orchestrator.discovery.scan)

    # Start Native Messaging and Gateway as background tasks
    _safe_create_task(orchestrator.adapters["messaging"].start())
    _safe_create_task(orchestrator.adapters["gateway"].start())

    try:
        await orchestrator.adapters["openclaw"].connect(on_event=orchestrator.on_openclaw_event)
        await orchestrator.adapters["openclaw"].subscribe_events(["chat.message", "tool.call"])
        print("Connected to OpenClaw Gateway.")
    except Exception as e:
        print(f"Failed to connect to OpenClaw: {e}")

    try:
        await orchestrator.adapters["mcp"].start_all()
        print("MCP Servers started.")
    except Exception as e:
        print(f"Failed to start MCP Servers: {e}")

    # Initialize Project RAG
    try:
        await orchestrator.rag.build_index()
        print(f"Project RAG index built for: {orchestrator.rag.root_dir}")
    except Exception as e:
        print(f"Failed to build RAG index: {e}")

    # Start background tasks (sync, proactive, pruning, backup)
    await orchestrator.background_tasks.start_all_tasks()

    # Start resource guard (RAM/VRAM monitoring)
    try:
        await orchestrator.resource_guard.start()
        print("ResourceGuard started.")
    except Exception as e:
        print(f"Failed to start ResourceGuard: {e}")

    # Start central health monitor loop
    coro = None
    try:
        coro = orchestrator.health_monitor.start_monitoring()
        task = asyncio.create_task(coro)
        coro = None  # create_task consumed the coroutine
        orchestrator._health_task = task
    except Exception:
        orchestrator._health_task = None
        if coro is not None and hasattr(coro, "close"):
            try:
                coro.close()
            except Exception:
                pass


async def shutdown(orchestrator: "MegaBotOrchestrator") -> None:
    """Gracefully shutdown the orchestrator and all adapters.

    Args:
        orchestrator: The MegaBotOrchestrator instance to shut down.
    """
    print("[MegaBot] Shutting down orchestrator...")

    # Close LLM provider session (PERF-06: prevent resource leak)
    if hasattr(orchestrator, "llm") and hasattr(orchestrator.llm, "close"):
        try:
            await orchestrator.llm.close()
            print("[MegaBot] LLM provider session closed")
        except Exception as e:
            print(f"[MegaBot] Error closing LLM provider: {e}")

    # Close memory server (thread pool + SQLite connections)
    if hasattr(orchestrator, "memory") and hasattr(orchestrator.memory, "close"):
        try:
            await orchestrator.memory.close()
            print("[MegaBot] Memory server closed")
        except Exception as e:
            print(f"[MegaBot] Error closing memory server: {e}")

    # Shutdown all adapters
    for name, adapter in orchestrator.adapters.items():  # pragma: no cover
        try:  # pragma: no cover
            if hasattr(adapter, "shutdown"):  # pragma: no cover
                await adapter.shutdown()  # pragma: no cover
                print(f"[MegaBot] Adapter '{name}' shutdown complete")
            elif hasattr(adapter, "close"):
                await adapter.close()
                print(f"[MegaBot] Adapter '{name}' closed")
        except Exception as e:
            print(f"[MegaBot] Error shutting down adapter '{name}': {e}")

    # Cancel health monitoring task
    health_task = getattr(orchestrator, "_health_task", None)
    if health_task is not None:
        if isinstance(health_task, asyncio.Task):
            health_task.cancel()
            try:
                await health_task
            except (asyncio.CancelledError, Exception):
                pass
        else:
            # Not a real Task (e.g. mock); close any underlying coroutine
            # discovered via __await__.__self__ to avoid resource warnings.
            try:
                await_fn = getattr(health_task, "__await__", None)
                if await_fn:
                    coro = getattr(await_fn, "__self__", None)
                    if coro and hasattr(coro, "close"):
                        coro.close()
            except Exception:
                pass

    # Shutdown background tasks
    if hasattr(orchestrator, "background_tasks") and orchestrator.background_tasks:
        try:
            shutdown_coro = orchestrator.background_tasks.shutdown()
            if asyncio.iscoroutine(shutdown_coro):
                await shutdown_coro
        except Exception:
            pass

    # Shutdown health monitor (cancel its internal tasks)
    if hasattr(orchestrator, "health_monitor") and orchestrator.health_monitor:
        try:
            await orchestrator.health_monitor.shutdown()
        except Exception:
            pass

    # Stop resource guard
    if hasattr(orchestrator, "resource_guard") and orchestrator.resource_guard:
        try:
            await orchestrator.resource_guard.stop()
            print("[MegaBot] ResourceGuard stopped")
        except Exception as e:
            print(f"[MegaBot] Error stopping ResourceGuard: {e}")

    # Close all WebSocket connections  # pragma: no cover
    for client in list(orchestrator.clients):  # pragma: no cover
        try:
            await client.close()
        except Exception:
            pass
    orchestrator.clients.clear()

    print("[MegaBot] Orchestrator shutdown complete")


async def restart_component(orchestrator: "MegaBotOrchestrator", name: str) -> None:  # pragma: no cover
    """Attempt to re-initialize or reconnect a specific system component.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        name: Name of the component to restart (openclaw, messaging, mcp, gateway).
    """
    print(f"Self-Healing: Restarting {name}...")
    try:
        if name == "openclaw":
            await orchestrator.adapters["openclaw"].connect(on_event=orchestrator.on_openclaw_event)
            await orchestrator.adapters["openclaw"].subscribe_events(["chat.message", "tool.call"])
        elif name == "messaging":
            _safe_create_task(orchestrator.adapters["messaging"].start())
        elif name == "mcp":
            await orchestrator.adapters["mcp"].start_all()
        elif name == "gateway":
            _safe_create_task(orchestrator.adapters["gateway"].start())
        print(f"Self-Healing: {name} restart initiated.")
    except Exception as e:
        print(f"Self-Healing Error: Failed to restart {name}: {e}")
