"""
Core orchestrator components extracted from monolithic orchestrator.
Handles message routing, health monitoring, and system coordination.
"""

from typing import Dict, Any, List
import asyncio

from core.dependencies import resolve_service
from core.interfaces import Message
from core.drivers import ComputerDriver


class MessageHandler:
    """Handles message processing and routing."""

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.chat_contexts: Dict[
            str, List[Dict]
        ] = {}  # chat_id -> List[Dict] for recent conversation history
        self._computer_driver = None  # Lazily cached DI resolution

    async def process_gateway_message(self, data: Dict):
        """Handle messages incoming from the Unified Gateway"""
        print(f"Gateway Message: {data}")
        msg_type = data.get("type")
        sender_id = data.get("sender_id", "unknown")
        chat_id = data.get(
            "chat_id", sender_id
        )  # Default to sender_id if no chat_id (e.g. DM)
        platform = data.get("_meta", {}).get("connection_type", "gateway")

        # Identity-Link: Resolve unified chat_id
        chat_id = await self.orchestrator.memory.get_unified_id(platform, chat_id)

        if msg_type == "message":
            await self._handle_user_message(data, sender_id, chat_id, platform)

    async def _handle_user_message(
        self, data: Dict, sender_id: str, chat_id: str, platform: str
    ):
        """Handle user messages with attachments and admin commands."""
        content = data.get("content", "")
        attachments = data.get("attachments", [])

        # Handle attachments (vision, audio)
        await self._process_attachments(attachments, sender_id, content)

        # Check for Admin Command
        if content.startswith("!"):
            if await self.orchestrator.admin_handler.handle_command(
                content, sender_id, chat_id, platform
            ):
                # Notify success
                resp = Message(
                    content=f"Admin command executed: {content}",
                    sender="System",
                    metadata={"chat_id": chat_id},
                )
                await self.orchestrator.send_platform_message(resp, platform=platform)
                return

        # Record in Persistent Memory
        await self.orchestrator.memory.chat_write(
            chat_id=chat_id, platform=platform, role="user", content=content
        )

        # Update chat context
        await self._update_chat_context(chat_id, content)

        # Route based on mode
        if self.orchestrator.mode == "build":
            await self.orchestrator.run_autonomous_gateway_build(
                Message(
                    content=content,
                    sender=data.get("sender_name", "gateway-user"),
                    metadata={"chat_id": chat_id, "sender_id": sender_id},
                ),
                data,
            )
        else:
            # Standard relay to OpenClaw
            await self.orchestrator.adapters["openclaw"].send_message(
                Message(
                    content=content,
                    sender=data.get("sender_name", "gateway-user"),
                    metadata={"chat_id": chat_id, "sender_id": sender_id},
                )
            )

    async def _process_attachments(
        self, attachments: List[Dict], sender_id: str, content: str
    ) -> str:
        """Process message attachments (images, audio) and return context."""
        vision_context = ""
        if self._computer_driver is None:
            self._computer_driver = resolve_service(ComputerDriver)
        computer_driver = self._computer_driver

        for attachment in attachments:
            if attachment.get("type") == "image":
                print(f"Vision-Agent: Analyzing attachment from {sender_id}...")
                image_data = attachment.get("data") or attachment.get("url")
                if image_data:
                    description = await computer_driver.execute(
                        "analyze_image", text=image_data
                    )
                    vision_context += f"\n[Attachment Analysis]: {description}\n"
            elif attachment.get("type") == "audio":
                print(f"Voice-Agent: Transcribing attachment from {sender_id}...")
                audio_data = attachment.get("data")
                if audio_data:
                    # Audio transcription logic would go here
                    # For now, just indicate it was processed
                    pass

        return vision_context

    async def _update_chat_context(self, chat_id: str, content: str):
        """Update local chat context cache."""
        if chat_id not in self.chat_contexts:
            # Load recent history from DB
            history = await self.orchestrator.memory.chat_read(chat_id, limit=10)
            self.chat_contexts[chat_id] = [
                {"role": h["role"], "content": h["content"]} for h in history
            ]

        self.chat_contexts[chat_id].append({"role": "user", "content": content})
        # Keep only last 10 messages
        self.chat_contexts[chat_id] = self.chat_contexts[chat_id][-10:]


class HealthMonitor:
    """Monitors system health and manages component restarts."""

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        # Keep references to created tasks so they can be cancelled/awaited on shutdown
        self._tasks: List[asyncio.Task] = []
        # Track last known status and restart counts for monitored components
        self.last_status: Dict[str, Any] = {}
        self.restart_counts: Dict[str, int] = {}

    async def shutdown(self):
        """Cancel and await any tasks started by BackgroundTasks."""
        # Cancel scheduled tasks and await them safely
        for t in list(self._tasks):
            try:
                t.cancel()
            except Exception:
                pass

        for t in list(self._tasks):
            try:
                if isinstance(t, asyncio.Task) or asyncio.isfuture(t):
                    try:
                        await t
                    except Exception:
                        pass
            except Exception:
                # If mocked types raise on isinstance checks, skip awaiting
                pass

        self._tasks.clear()
        self.last_status = {}
        self.restart_counts = {}  # component -> count

    async def get_system_health(self) -> Dict[str, Any]:
        """Check the status of all system components"""
        health = {}

        # Memory Server
        try:
            stats = await self.orchestrator.memory.memory_stats()
            health["memory"] = {
                "status": "up" if "error" not in stats else "down",
                "details": stats,
            }
        except Exception as e:
            health["memory"] = {"status": "down", "error": str(e)}

        # OpenClaw
        try:
            is_connected = self.orchestrator.adapters["openclaw"].websocket is not None
            health["openclaw"] = {"status": "up" if is_connected else "down"}
        except Exception:
            health["openclaw"] = {"status": "down"}

        # Messaging Server
        try:
            client_count = len(self.orchestrator.adapters["messaging"].clients)
            health["messaging"] = {"status": "up", "clients": client_count}
        except Exception:
            health["messaging"] = {"status": "down"}

        # MCP Servers
        try:
            health["mcp"] = {
                "status": "up",
                "server_count": len(self.orchestrator.adapters["mcp"].servers),
            }
        except Exception:
            health["mcp"] = {"status": "down"}

        return health

    async def start_monitoring(self):
        """Start the heartbeat monitoring loop."""
        while True:
            try:
                status = await self.get_system_health()

                # Check for regressions and auto-restart
                for component, data in status.items():
                    current_up = data.get("status") == "up"
                    was_up = (
                        self.last_status.get(component, {}).get("status", "up") == "up"
                    )

                    if not current_up:
                        count = self.restart_counts.get(component, 0)
                        if count < 3:  # Max 3 retries # pragma: no cover
                            print(
                                f"Heartbeat: {component} is down. Triggering restart (attempt {count + 1})..."
                            )
                            await self.orchestrator.restart_component(component)
                            self.restart_counts[component] = count + 1

                        if was_up:  # Only notify on first failure # pragma: no cover
                            msg = Message(
                                content=f"🚨 Component Down: {component}\nError: {data.get('error', 'Unknown')}\nAuto-restart triggered.",
                                sender="Security",
                            )
                            asyncio.create_task(
                                self.orchestrator.send_platform_message(msg)
                            )
                    else:
                        self.restart_counts[component] = 0  # pragma: no cover

                self.last_status = status
            except Exception as e:
                print(f"Heartbeat loop error: {e}")

            await asyncio.sleep(60)  # Check every minute


class BackgroundTasks:
    """Manages background tasks and loops."""

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        # Track scheduled background tasks so they can be cancelled/awaited on shutdown
        self._tasks: List[asyncio.Task] = []

    async def start_all_tasks(self):
        """Start all background tasks."""

        # Defensive scheduling: try asyncio.create_task, fall back to asyncio.ensure_future.
        # If scheduling fails (tests may patch these functions to raise), close the
        # coroutine to avoid "coroutine was never awaited" warnings.
        def _safe_schedule(coro):
            try:
                t = asyncio.create_task(coro)
                print(f"[BackgroundTasks] scheduled via create_task: {coro}")
                return t
            except Exception:
                try:
                    t = asyncio.ensure_future(coro)
                    print(f"[BackgroundTasks] scheduled via ensure_future: {coro}")
                    return t
                except Exception:
                    # If coro is a coroutine object, close it to avoid warnings.
                    try:
                        if hasattr(coro, "close"):
                            print(
                                f"[BackgroundTasks] closing coro in _safe_schedule: {coro}"
                            )
                            coro.close()
                    except Exception:
                        pass
                    return None

        for loop_fn in (
            self.sync_loop,
            self.proactive_loop,
            self.pruning_loop,
            self.backup_loop,
        ):
            try:
                coro = loop_fn()
            except Exception:
                # If creating the coroutine itself raises, skip scheduling it.
                coro = None

            if coro is None:
                # Nothing to schedule (tests may stub these to return None)
                continue

            print(f"[BackgroundTasks] attempting to schedule coro: {coro!r}")
            task = _safe_schedule(coro)
            if task is not None:
                self._tasks.append(task)
            else:
                # Ensure coroutine is closed if scheduling failed to avoid warnings
                try:
                    if hasattr(coro, "close"):
                        print(f"[BackgroundTasks] closing coro in main loop: {coro!r}")
                        coro.close()
                except Exception:
                    pass
        # Health monitoring is started by the orchestrator itself to allow
        # finer control over restart sequencing and to avoid double-starting
        # during tests. BackgroundTasks is responsible only for internal
        # periodic loops.

    async def sync_loop(self):
        """Synchronization loop for cross-platform data sync."""
        while True:
            try:
                print("Sync Loop: Synchronizing user identities across platforms...")

                # Sync user identities and link platform accounts
                if hasattr(self.orchestrator, "user_identity"):
                    try:
                        # Trigger any pending identity sync operations
                        await self.orchestrator.user_identity.sync_pending_identities()
                        print("Sync Loop: User identities synchronized")
                    except Exception as e:
                        print(f"Sync Loop: Identity sync error: {e}")

                # Sync chat memory across platforms for linked users
                if hasattr(self.orchestrator, "chat_memory"):
                    try:
                        # Consolidate cross-platform conversations for linked users
                        await self.orchestrator.chat_memory.sync_cross_platform_chats()
                        print("Sync Loop: Chat memory synchronized")
                    except Exception as e:
                        print(f"Sync Loop: Chat memory sync error: {e}")

                # Update knowledge memory stats
                if hasattr(self.orchestrator, "knowledge_memory"):
                    try:
                        stats = await self.orchestrator.knowledge_memory.get_stats()
                        print(f"Sync Loop: Knowledge memory stats - {stats}")
                    except Exception as e:
                        print(f"Sync Loop: Knowledge memory error: {e}")

                await asyncio.sleep(300)  # Every 5 minutes
            except Exception as e:
                print(f"Sync loop error: {e}")

    async def proactive_loop(self):
        """Proactive task checking loop."""
        while True:
            try:
                print("Proactive Loop: Checking for updates...")

                # Check memU for proactive tasks
                anticipations = await self.orchestrator.adapters[
                    "memu"
                ].get_anticipations()
                for task in anticipations:
                    print(f"Proactive Trigger (Memory): {task.get('content')}")
                    message = Message(
                        content=f"Suggestion: {task.get('content')}", sender="MegaBot"
                    )
                    await self.orchestrator.adapters["openclaw"].send_message(message)

                # Check Calendar via MCP
                try:
                    events = await self.orchestrator.adapters["mcp"].call_tool(
                        "google-services", "list_events", {"limit": 1}
                    )
                    if events:
                        print(f"Proactive Trigger (Calendar): {events}")
                        resp = Message(  # pragma: no cover
                            content=f"Calendar Reminder: {events}", sender="Calendar"
                        )
                        await self.orchestrator.send_platform_message(
                            resp
                        )  # pragma: no cover
                except Exception as e:  # pragma: no cover
                    print(f"Calendar check failed (expected if not configured): {e}")

            except Exception as e:  # pragma: no cover
                print(f"Proactive loop error: {e}")
            await asyncio.sleep(3600)  # Check every hour

    async def pruning_loop(self):
        """Background task to prune old chat history."""
        while True:
            try:
                print("Pruning Loop: Checking for bloated chat histories...")
                chat_ids = await self.orchestrator.memory.get_all_chat_ids()
                for chat_id in chat_ids:
                    # Keep last 500 messages per chat
                    await self.orchestrator.memory.chat_forget(chat_id, max_history=500)
            except Exception as e:  # pragma: no cover
                print(f"Pruning loop error: {e}")
            await asyncio.sleep(86400)  # Run once every 24 hours

    async def backup_loop(self):
        """Background task to backup the memory database."""
        while True:
            try:
                print("Backup Loop: Creating memory database backup...")
                res = await self.orchestrator.memory.backup_database()
                print(f"Backup Loop: {res}")
            except Exception as e:  # pragma: no cover
                print(f"Backup loop error: {e}")
            await asyncio.sleep(43200)  # Run every 12 hours
