"""
Admin command processing for MegaBot orchestrator.
Handles administrative commands and system management.
"""

from typing import Dict, Optional
import asyncio
import shlex
import os
from pathlib import Path

from core.interfaces import Message


class AdminHandler:
    """Handles administrative commands and system management."""

    # Allowlist of safe commands that can be executed via system_command.
    # Each entry is the base executable name (no path, no args).
    ALLOWED_COMMANDS = {
        "ls",
        "cat",
        "head",
        "tail",
        "df",
        "du",
        "free",
        "uptime",
        "whoami",
        "date",
        "ps",
        "top",
        "echo",
        "wc",
        "uname",
        "pip",
        "python",
        "node",
        "npm",
        "git",
    }

    # Allowed base directory for file_operation (resolved to absolute).
    # Restricts file reads/writes to the project root and below.
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.approval_queue = []  # Queue for sensitive actions

    async def handle_command(
        self,
        text: str,
        sender_id: str,
        chat_id: Optional[str] = None,
        platform: str = "native",
    ) -> bool:
        """Process chat-based administrative commands"""
        # Check if sender is an admin
        if (
            not self.orchestrator.config.admins
            or sender_id not in self.orchestrator.config.admins
        ):
            return False

        parts = text.strip().split()
        if not parts:
            return False
        cmd = parts[0].lower()

        # Command routing
        command_map = {
            "!approve": self._handle_approve,
            "!yes": self._handle_approve,
            "!reject": self._handle_reject,
            "!no": self._handle_reject,
            "!allow": self._handle_allow,
            "!deny": self._handle_deny,
            "!policies": self._handle_policies,
            "!mode": self._handle_mode,
            "!history_clean": self._handle_history_clean,
            "!link": self._handle_link,
            "!whoami": self._handle_whoami,
            "!backup": self._handle_backup,
            "!briefing": self._handle_briefing,
            "!rag_rebuild": self._handle_rag_rebuild,
            "!health": self._handle_health,
        }

        handler = command_map.get(cmd)
        if handler:
            return await handler(parts, sender_id, chat_id, platform)

        return False

    async def _handle_approve(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle approval commands."""
        action_id = (
            parts[1]
            if len(parts) > 1
            else (self.approval_queue[-1]["id"] if self.approval_queue else None)
        )
        if action_id:
            await self._process_approval(action_id, approved=True)
            return True
        return False

    async def _handle_reject(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle rejection commands."""
        action_id = (
            parts[1]
            if len(parts) > 1
            else (self.approval_queue[-1]["id"] if self.approval_queue else None)
        )
        if action_id:
            await self._process_approval(action_id, approved=False)
            return True
        return False

    async def _handle_allow(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle allow policy commands."""
        if len(parts) > 1:
            pattern = " ".join(parts[1:])
            if pattern not in self.orchestrator.config.policies.get("allow", []):
                if "allow" not in self.orchestrator.config.policies:
                    self.orchestrator.config.policies["allow"] = []
                self.orchestrator.config.policies["allow"].append(pattern)
                self.orchestrator.config.save()
                print(f"Policy Update: Allowed '{pattern}' (Persisted)")
                return True
        return False

    async def _handle_deny(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle deny policy commands."""
        if len(parts) > 1:
            pattern = " ".join(parts[1:])
            if pattern not in self.orchestrator.config.policies.get("deny", []):
                if "deny" not in self.orchestrator.config.policies:
                    self.orchestrator.config.policies["deny"] = []
                self.orchestrator.config.policies["deny"].append(pattern)
                self.orchestrator.config.save()
                print(f"Policy Update: Denied '{pattern}' (Persisted)")
                return True
        return False

    async def _handle_policies(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        resp_text = f"Policies:\nAllow: {self.orchestrator.config.policies['allow']}\nDeny: {self.orchestrator.config.policies['deny']}"
        resp = Message(
            content=resp_text, sender="System", metadata={"chat_id": chat_id}
        )
        asyncio.create_task(self.orchestrator.send_platform_message(resp))
        return True

    async def _handle_mode(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle mode switching commands."""
        if len(parts) > 1:
            self.orchestrator.mode = parts[1]
            print(f"System Mode updated to: {self.orchestrator.mode}")
            if self.orchestrator.mode == "loki":
                asyncio.create_task(
                    self.orchestrator.loki.activate("Auto-trigger from chat")
                )
            return True
        return False

    async def _handle_history_clean(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle history cleaning commands."""
        target_chat = parts[1] if len(parts) > 1 else chat_id
        if target_chat:
            await self.orchestrator.memory.chat_forget(target_chat, max_history=0)
            resp = Message(
                content=f"🗑️ History cleaned for chat: {target_chat}",
                sender="System",
            )
            asyncio.create_task(
                self.orchestrator.send_platform_message(resp, chat_id=chat_id)
            )
            return True
        return False

    async def _handle_link(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle identity linking commands."""
        if len(parts) > 1:
            target_name = parts[1]
            await self.orchestrator.memory.link_identity(
                target_name, platform, sender_id
            )
            resp = Message(
                content=f"🔗 Identity Linked: {platform}:{sender_id} is now known as '{target_name}'",
                sender="System",
            )
            asyncio.create_task(
                self.orchestrator.send_platform_message(
                    resp, chat_id=chat_id, platform=platform
                )
            )
            return True
        return False

    async def _handle_whoami(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle identity query commands."""
        unified = await self.orchestrator.memory.get_unified_id(platform, sender_id)
        resp = Message(
            content=f"👤 Identity Info:\nPlatform: {platform}\nID: {sender_id}\nUnified: {unified}",
            sender="System",
        )
        asyncio.create_task(
            self.orchestrator.send_platform_message(
                resp, chat_id=chat_id, platform=platform
            )
        )
        return True

    async def _handle_backup(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle backup commands."""
        res = await self.orchestrator.memory.backup_database()
        resp = Message(content=f"💾 Backup Triggered: {res}", sender="System")
        asyncio.create_task(
            self.orchestrator.send_platform_message(
                resp, chat_id=chat_id, platform=platform
            )
        )
        return True

    async def _handle_briefing(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle voice briefing commands."""
        admin_phone = getattr(self.orchestrator.config.system, "admin_phone", None)
        if not admin_phone or not self.orchestrator.adapters["messaging"].voice_adapter:
            resp = Message(
                content="❌ Briefing failed: No admin phone or voice adapter configured.",
                sender="System",
            )
            asyncio.create_task(
                self.orchestrator.send_platform_message(
                    resp, chat_id=chat_id, platform=platform
                )
            )
            return True

        asyncio.create_task(
            self._trigger_voice_briefing(admin_phone, chat_id or "", platform)
        )
        resp = Message(
            content="📞 Voice briefing initiated. Expect a call shortly.",
            sender="System",
        )
        asyncio.create_task(
            self.orchestrator.send_platform_message(
                resp, chat_id=chat_id, platform=platform
            )
        )
        return True

    async def _handle_rag_rebuild(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle RAG rebuild commands."""
        await self.orchestrator.rag.build_index(force_rebuild=True)
        resp = Message(content="🏗️ RAG Index rebuilt and cached.", sender="System")
        asyncio.create_task(
            self.orchestrator.send_platform_message(
                resp, chat_id=chat_id, platform=platform
            )
        )
        return True

    async def _handle_health(
        self, parts: list, sender_id: str, chat_id: Optional[str], platform: str
    ) -> bool:
        """Handle health check commands."""
        health = await self.orchestrator.health_monitor.get_system_health()
        health_text = "🩺 **System Health:**\n"
        for comp, data in health.items():
            status_emoji = "✅" if data["status"] == "up" else "❌"
            health_text += (
                f"- {status_emoji} **{comp.capitalize()}**: {data['status']}\n"
            )
            if "error" in data:
                health_text += f"  - Error: {data['error']}\n"

        resp = Message(content=health_text, sender="System")
        asyncio.create_task(
            self.orchestrator.send_platform_message(
                resp, chat_id=chat_id, platform=platform
            )
        )
        return True

    async def _process_approval(self, action_id: str, approved: bool):
        """Process approval/rejection of queued actions."""
        # Find and remove the action
        action = None
        for a in self.approval_queue:
            if a["id"] == action_id:
                action = a
                self.approval_queue.remove(a)
                break

        if not action:
            return

        if approved:
            print(f"✅ Action approved: {action['description']}")
            # Execute the approved action
            await self._execute_approved_action(action)
        else:
            print(f"❌ Action rejected: {action['description']}")

    async def _execute_approved_action(self, action: Dict):
        """Execute an approved action based on its type."""
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        print(f"🔧 Executing approved action: {action.get('description', action_type)}")

        try:
            if action_type == "system_command":
                import subprocess

                command = payload.get("params", {}).get("command", "")
                if not command:
                    return "No command provided"

                # Parse with shlex to avoid shell injection; reject unparseable input
                try:
                    args = shlex.split(command)
                except ValueError as e:
                    return f"❌ Invalid command syntax: {e}"

                if not args:
                    return "No command provided"

                # Validate executable against allowlist
                executable = os.path.basename(args[0])
                if executable not in self.ALLOWED_COMMANDS:
                    msg = f"❌ Command '{executable}' is not in the allowed list: {sorted(self.ALLOWED_COMMANDS)}"
                    print(msg)
                    return msg

                # Execute without shell=True to prevent injection
                result = subprocess.run(
                    args, shell=False, capture_output=True, text=True, timeout=30
                )
                output = result.stdout if result.returncode == 0 else result.stderr
                print(f"✅ Command executed:\n{output}")

                # Send result back via WebSocket if available
                websocket = action.get("websocket")
                if websocket:
                    await websocket.send_json(
                        {
                            "type": "command_result",
                            "command": command,
                            "output": output,
                            "success": result.returncode == 0,
                        }
                    )
                return output

            elif action_type == "mcp_tool":
                # Execute MCP tool
                server = payload.get("server")
                tool = payload.get("tool")
                params = payload.get("params", {})

                if (
                    hasattr(self.orchestrator, "adapters")
                    and "mcp" in self.orchestrator.adapters
                ):
                    result = await self.orchestrator.adapters["mcp"].call_tool(
                        server, tool, params
                    )
                    print(f"✅ MCP tool executed: {result}")
                    return result

            elif action_type == "file_operation":
                # File read/write operations — restricted to PROJECT_ROOT
                operation = payload.get("operation")
                raw_path = payload.get("path", "")
                content = payload.get("content", "")

                if not raw_path:
                    return "❌ No file path provided"

                # Resolve to absolute and ensure it's within PROJECT_ROOT
                resolved = Path(raw_path).resolve()
                if not str(resolved).startswith(str(self.PROJECT_ROOT)):
                    msg = f"❌ Path traversal blocked: '{raw_path}' resolves outside project root"
                    print(msg)
                    return msg

                if operation == "read":
                    with open(resolved, "r") as f:
                        return f.read()
                elif operation == "write":
                    with open(resolved, "w") as f:
                        f.write(content)
                    return f"File written: {resolved}"
                else:
                    return f"❌ Unknown file operation: {operation}"

            else:
                # Generic action - try to route through OpenClaw if available
                if (
                    hasattr(self.orchestrator, "adapters")
                    and "openclaw" in self.orchestrator.adapters
                ):
                    method = payload.get("method", "")
                    params = payload.get("params", {})
                    result = await self.orchestrator.adapters["openclaw"].execute_tool(
                        method, params
                    )
                    print(f"✅ Action executed via OpenClaw: {result}")
                    return result
                else:
                    print(f"⚠️ Unknown action type: {action_type}")

        except Exception as e:
            error_msg = f"❌ Action execution failed: {e}"
            print(error_msg)

            # Send error back via WebSocket if available
            websocket = action.get("websocket")
            if websocket:
                await websocket.send_json(
                    {
                        "type": "action_error",
                        "error": str(e),
                        "action": action.get("description", "Unknown"),
                    }
                )
            return error_msg

    async def _trigger_voice_briefing(self, phone: str, chat_id: str, platform: str):
        """Generate a summary of recent events and call the admin to read it"""
        try:
            # 1. Fetch recent activity
            history = await self.orchestrator.memory.chat_read(chat_id, limit=20)
            if not history:
                script = "This is Mega Bot. No recent activity to report."
            else:
                # 2. Summarize
                history_text = "\n".join(
                    [f"{h['role']}: {h['content']}" for h in history]
                )
                summary_prompt = f"Summarize the following recent bot activity for a short voice briefing (max 50 words). Focus on completed tasks or pending approvals:\n\n{history_text}"
                summary = await self.orchestrator.llm.generate(
                    context="Voice Briefing",
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                script = f"Hello, this is Mega Bot. Here is your recent activity briefing: {summary}"

            # 3. Make the call
            await self.orchestrator.adapters["messaging"].voice_adapter.make_call(
                phone, script
            )
        except Exception as e:
            print(f"Voice briefing failed: {e}")
