"""
Admin command processing for MegaBot orchestrator.
Handles administrative commands and system management.
"""

from typing import Dict, Optional
import asyncio
import logging
import shlex
import os
import tempfile
from pathlib import Path

from core.interfaces import Message
from core.task_utils import safe_create_task

logger = logging.getLogger(__name__)


class AdminHandler:
    """Handles administrative commands and system management."""

    # Allowlist of safe commands that can be executed via system_command.
    # Each entry is the base executable name (no path, no args).
    # Allowlist restricted to read-only / informational commands.
    # python, node, npm, pip, and git are EXCLUDED because they allow
    # arbitrary code execution (e.g. python -c "import os; os.system('...')").
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
        if not self.orchestrator.config.admins or sender_id not in self.orchestrator.config.admins:
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

    async def _handle_approve(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle approval commands."""
        action_id = parts[1] if len(parts) > 1 else (self.approval_queue[-1]["id"] if self.approval_queue else None)
        if action_id:
            await self._process_approval(action_id, approved=True)
            return True
        return False

    async def _handle_reject(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle rejection commands."""
        action_id = parts[1] if len(parts) > 1 else (self.approval_queue[-1]["id"] if self.approval_queue else None)
        if action_id:
            await self._process_approval(action_id, approved=False)
            return True
        return False

    async def _handle_allow(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle allow policy commands."""
        if len(parts) > 1:
            pattern = " ".join(parts[1:])
            if pattern not in self.orchestrator.config.policies.get("allow", []):
                if "allow" not in self.orchestrator.config.policies:
                    self.orchestrator.config.policies["allow"] = []
                self.orchestrator.config.policies["allow"].append(pattern)
                self.orchestrator.config.save()
                logger.info("Policy Update: Allowed '%s' (Persisted)", pattern)
                return True
        return False

    async def _handle_deny(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle deny policy commands."""
        if len(parts) > 1:
            pattern = " ".join(parts[1:])
            if pattern not in self.orchestrator.config.policies.get("deny", []):
                if "deny" not in self.orchestrator.config.policies:
                    self.orchestrator.config.policies["deny"] = []
                self.orchestrator.config.policies["deny"].append(pattern)
                self.orchestrator.config.save()
                logger.info("Policy Update: Denied '%s' (Persisted)", pattern)
                return True
        return False

    async def _handle_policies(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        resp_text = f"Policies:\nAllow: {self.orchestrator.config.policies['allow']}\nDeny: {self.orchestrator.config.policies['deny']}"
        resp = Message(content=resp_text, sender="System", metadata={"chat_id": chat_id})
        safe_create_task(self.orchestrator.send_platform_message(resp))
        return True

    async def _handle_mode(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle mode switching commands."""
        if len(parts) > 1:
            self.orchestrator.mode = parts[1]
            logger.info("System Mode updated to: %s", self.orchestrator.mode)
            if self.orchestrator.mode == "loki":
                safe_create_task(self.orchestrator.loki.activate("Auto-trigger from chat"))
            return True
        return False

    async def _handle_history_clean(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle history cleaning commands."""
        target_chat = parts[1] if len(parts) > 1 else chat_id
        if target_chat:
            await self.orchestrator.memory.chat_forget(target_chat, max_history=0)
            resp = Message(
                content=f"🗑️ History cleaned for chat: {target_chat}",
                sender="System",
            )
            safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id))
            return True
        return False

    async def _handle_link(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle identity linking commands."""
        if len(parts) > 1:
            target_name = parts[1]
            await self.orchestrator.memory.link_identity(target_name, platform, sender_id)
            resp = Message(
                content=f"🔗 Identity Linked: {platform}:{sender_id} is now known as '{target_name}'",
                sender="System",
            )
            safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
            return True
        return False

    async def _handle_whoami(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle identity query commands."""
        unified = await self.orchestrator.memory.get_unified_id(platform, sender_id)
        resp = Message(
            content=f"👤 Identity Info:\nPlatform: {platform}\nID: {sender_id}\nUnified: {unified}",
            sender="System",
        )
        safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
        return True

    async def _handle_backup(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle backup commands."""
        res = await self.orchestrator.memory.backup_database()
        resp = Message(content=f"💾 Backup Triggered: {res}", sender="System")
        safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
        return True

    async def _handle_briefing(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle voice briefing commands."""
        admin_phone = getattr(self.orchestrator.config.system, "admin_phone", None)
        if not admin_phone or not self.orchestrator.adapters["messaging"].voice_adapter:
            resp = Message(
                content="❌ Briefing failed: No admin phone or voice adapter configured.",
                sender="System",
            )
            safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
            return True

        safe_create_task(self._trigger_voice_briefing(admin_phone, chat_id or "", platform))
        resp = Message(
            content="📞 Voice briefing initiated. Expect a call shortly.",
            sender="System",
        )
        safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
        return True

    async def _handle_rag_rebuild(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle RAG rebuild commands."""
        await self.orchestrator.rag.build_index(force_rebuild=True)
        resp = Message(content="🏗️ RAG Index rebuilt and cached.", sender="System")
        safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
        return True

    async def _handle_health(self, parts: list, sender_id: str, chat_id: Optional[str], platform: str) -> bool:
        """Handle health check commands."""
        health = await self.orchestrator.health_monitor.get_system_health()
        health_text = "🩺 **System Health:**\n"
        for comp, data in health.items():
            status_emoji = "✅" if data["status"] == "up" else "❌"
            health_text += f"- {status_emoji} **{comp.capitalize()}**: {data['status']}\n"
            if "error" in data:
                health_text += f"  - Error: {data['error']}\n"

        resp = Message(content=health_text, sender="System")
        safe_create_task(self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
        return True

    async def _process_approval(self, action_id: str, approved: bool):
        """Process approval/rejection of queued actions.

        SEC-FIX-002: This is now the single source of truth for approval
        processing. The orchestrator delegates here to ensure that all
        actions go through the ALLOWED_COMMANDS allowlist and other
        security checks.
        """
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
            logger.info("Action approved: %s", action.get("description", action.get("type", action_id)))
            # Execute the approved action
            await self._execute_approved_action(action)
        else:
            logger.info("Action rejected: %s", action.get("description", action.get("type", action_id)))
            # Notify the callback of denial (SEC-FIX-002: migrated from orchestrator)
            if "callback" in action and callable(action["callback"]):
                try:
                    await action["callback"]("Action denied by user.")
                except Exception as e:
                    logger.error("Denial callback failed: %s", e)

    async def _execute_approved_action(self, action: Dict):
        """Execute an approved action based on its type."""
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        logger.info("Executing approved action: %s", action.get("description", action_type))

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
                    msg = f"Command '{executable}' is not in the allowed list: {sorted(self.ALLOWED_COMMANDS)}"
                    logger.warning("Blocked command: %s", msg)
                    return msg

                # Execute without shell=True to prevent injection
                result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=30)
                output = result.stdout if result.returncode == 0 else result.stderr
                logger.info("Command executed successfully:\n%s", output)

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

                if hasattr(self.orchestrator, "adapters") and "mcp" in self.orchestrator.adapters:
                    result = await self.orchestrator.adapters["mcp"].call_tool(server, tool, params)
                    logger.info("MCP tool executed: %s", result)
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
                try:
                    resolved.relative_to(self.PROJECT_ROOT)
                except ValueError:
                    msg = f"Path traversal blocked: '{raw_path}' resolves outside project root"
                    logger.warning("Path traversal blocked: %s", msg)
                    return msg

                if operation == "read":
                    with open(resolved, "r") as f:
                        return f.read()
                elif operation == "write":
                    # Atomic write: write to temp file then rename to avoid
                    # partial writes on crash/interrupt.
                    dir_path = resolved.parent
                    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
                    try:
                        with os.fdopen(fd, "w") as f:
                            f.write(content)
                        os.replace(tmp_path, str(resolved))
                    except BaseException:
                        # Clean up temp file on any failure
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                        raise
                    return f"File written: {resolved}"
                else:
                    return f"❌ Unknown file operation: {operation}"

            # --- SEC-FIX-002: Action types migrated from orchestrator ---

            elif action_type == "outbound_vision":
                from core.interfaces import Message as MsgType

                msg_content = payload.get("message_content", "")
                approved_msg = MsgType(
                    content=msg_content,
                    sender="MegaBot",
                    attachments=payload.get("attachments", []),
                )
                platform_msg = self.orchestrator._to_platform_message(
                    approved_msg,
                    chat_id=payload.get("chat_id"),
                )
                platform_msg.platform = payload.get("platform", "native")
                await self.orchestrator.adapters["messaging"].send_message(
                    platform_msg,
                    target_client=payload.get("target_client"),
                )
                logger.info(
                    "Outbound vision approved and sent to %s",
                    payload.get("chat_id"),
                )

            elif action_type == "data_execution":
                name = payload.get("name")
                code = payload.get("code")
                try:
                    from features.dash_data.agent import DashDataAgent
                    from core.interfaces import Message as MsgType

                    temp_agent = DashDataAgent(self.orchestrator.llm, self.orchestrator)
                    output = await temp_agent.execute_python_analysis(name, code)
                except Exception as e:
                    output = f"Approval execution failed: {e}"

                from core.interfaces import Message as MsgType

                resp = MsgType(
                    content=f"✅ Data Execution Result:\n{output}",
                    sender="DataAgent",
                )
                await self.orchestrator.send_platform_message(resp)

            elif action_type == "computer_use":
                comp_action = payload.get("action")
                coordinate = payload.get("coordinate")
                text = payload.get("text")

                output = await self.orchestrator.computer_driver.execute(comp_action, coordinate, text)
                logger.info("Computer Action Result: %s", output)

                ws = action.get("websocket")
                if ws:
                    if comp_action == "screenshot" and not output.startswith("Error"):
                        sent = await self.orchestrator._safe_ws_send(ws, {"type": "screenshot", "content": output})
                        if sent:
                            output = "Screenshot captured and sent to UI."
                    else:
                        await self.orchestrator._safe_ws_send(ws, {"type": "status", "content": output})

                await self.orchestrator.adapters["openclaw"].send_message(
                    {
                        "method": "tool.result",
                        "params": {"id": action["id"], "output": output},
                    }
                )

                if "callback" in action and callable(action["callback"]):
                    await action["callback"](output)

            elif action_type == "identity_link":
                internal_id = payload.get("internal_id")
                platform = payload.get("platform")
                platform_id = payload.get("platform_id")
                chat_id = payload.get("chat_id")

                if internal_id and platform and platform_id:
                    await self.orchestrator.memory.link_identity(internal_id, platform, platform_id)
                    from core.interfaces import Message as MsgType

                    resp = MsgType(
                        content=f"✅ Identity Link Verified: '{internal_id}' linked to {platform}:{platform_id}",
                        sender="System",
                    )
                    await self.orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform)

            else:
                # Generic action - try to route through OpenClaw if available
                if hasattr(self.orchestrator, "adapters") and "openclaw" in self.orchestrator.adapters:
                    method = payload.get("method", "")
                    params = payload.get("params", {})
                    result = await self.orchestrator.adapters["openclaw"].execute_tool(method, params)
                    logger.info("Action executed via OpenClaw: %s", result)
                    return result
                else:
                    logger.warning("Unknown action type: %s", action_type)

        except Exception as e:
            error_msg = f"Action execution failed: {e}"
            logger.error("Action execution failed: %s", e, exc_info=True)

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
                history_text = "\n".join([f"{h['role']}: {h['content']}" for h in history])
                summary_prompt = f"Summarize the following recent bot activity for a short voice briefing (max 50 words). Focus on completed tasks or pending approvals:\n\n{history_text}"
                summary = await self.orchestrator.llm.generate(
                    context="Voice Briefing",
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                script = f"Hello, this is Mega Bot. Here is your recent activity briefing: {summary}"

            # 3. Make the call
            await self.orchestrator.adapters["messaging"].voice_adapter.make_call(phone, script)
        except Exception as e:
            logger.error("Voice briefing failed", exc_info=True)
