"""OpenClaw event handling extracted from ``core/orchestrator.py``.

Contains the OpenClaw event router and the permission policy checker
that gates system/shell commands.
"""

import logging
import uuid
from typing import Dict, TYPE_CHECKING

from core.interfaces import Message
from core.task_utils import safe_create_task as _safe_create_task, sanitize_action as _sanitize_action
from core.constants import GREETING_TEXT

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Policy checking
# ------------------------------------------------------------------


def check_policy(orchestrator: "MegaBotOrchestrator", data: Dict) -> str:
    """Check if an action is pre-approved or pre-denied based on policies.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        data: The event data containing method and params.

    Returns:
        One of ``"allow"``, ``"deny"``, or ``"ask"``.
    """
    method = data.get("method")
    params = data.get("params", {})
    command = params.get("command", "")

    scope = str(method) if method else "unknown"
    if method in ["system.run", "shell.execute"] and command:
        for s in [f"shell.{command}", command]:
            auth = orchestrator.permissions.is_authorized(s)
            if auth is not None:
                return "allow" if auth else "deny"

        cmd_part = str(command).split()[0] if command else "unknown"
        for s in [f"shell.{cmd_part}", cmd_part]:
            auth = orchestrator.permissions.is_authorized(s)
            if auth is not None:
                return "allow" if auth else "deny"

    auth = orchestrator.permissions.is_authorized(scope)
    if auth is True:
        return "allow"
    if auth is False:
        return "deny"
    return "ask"


# ------------------------------------------------------------------
# Event router
# ------------------------------------------------------------------


async def on_openclaw_event(orchestrator: "MegaBotOrchestrator", data: Dict) -> None:
    """Handle events from the OpenClaw adapter.

    Routes events based on their ``method`` field:
    - ``connect`` / ``handshake``: sends greeting
    - ``chat.message`` with ``!`` prefix: admin command
    - ``system.run`` / ``shell.execute``: policy-gated approval
    - Everything else: relayed to UI clients

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        data: The event payload from OpenClaw.
    """
    logger.debug("OpenClaw Event: %s", data)
    method = data.get("method")
    params = data.get("params", {})
    sender_id = params.get("sender_id", "unknown")
    content = params.get("content", "")

    if method == "connect" or method == "handshake":
        greeting = Message(content=GREETING_TEXT, sender="MegaBot")
        await orchestrator.adapters["openclaw"].send_message(greeting)
        return

    if method == "chat.message" and content.startswith("!"):
        chat_id = params.get("chat_id") or sender_id
        platform = params.get("platform", "openclaw")
        if await orchestrator._handle_admin_command(content, sender_id, chat_id, platform):
            return

    if method == "system.run" or method == "shell.execute":
        policy = check_policy(orchestrator, data)

        if policy == "allow":
            logger.info("Policy: Auto-approving %s", method)
            await orchestrator.adapters["openclaw"].send_message(data)
            return

        if policy == "deny":
            logger.info("Policy: Auto-denying %s", method)
            return

        action = {
            "id": str(uuid.uuid4()),
            "type": "system_command",
            "payload": data,
            "description": f"Execute: {data.get('params', {}).get('command')}",
        }
        orchestrator.admin_handler.approval_queue.append(action)
        for client in list(orchestrator.clients):
            await client.send_json({"type": "approval_required", "action": _sanitize_action(action)})

        admin_resp = Message(
            content=f"Approval Required: {action['description']}\nType `!approve {action['id']}` to authorize.",
            sender="Security",
        )
        _safe_create_task(orchestrator.send_platform_message(admin_resp))
        return

    # Relay standard events to all connected UI clients
    for client in list(orchestrator.clients):
        try:
            await client.send_json({"type": "openclaw_event", "payload": data})
        except Exception:
            orchestrator.clients.discard(client)

    if data.get("method") == "chat.message":
        params = data.get("params", {})
        msg = Message(
            content=params.get("content", ""),
            sender=params.get("sender", "OpenClaw"),
        )
        await orchestrator.send_platform_message(msg)
