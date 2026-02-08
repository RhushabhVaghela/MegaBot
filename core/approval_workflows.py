"""Security approval workflow logic extracted from ``core/orchestrator.py``.

Contains approval escalation (voice call with DND/calendar awareness),
computer-use approval interlock, and identity-claim detection.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

from fastapi import WebSocket  # type: ignore

from core.interfaces import Message
from core.task_utils import safe_create_task as _safe_create_task, sanitize_action as _sanitize_action

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator


# ------------------------------------------------------------------
# Approval escalation
# ------------------------------------------------------------------


async def start_approval_escalation(orchestrator: "MegaBotOrchestrator", action: Dict) -> None:
    """Escalate via Voice Call if approval is not received within 5 minutes.

    Checks DND hours (static config) and dynamic calendar events before
    initiating the call.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        action: The approval action dict (must contain ``id``).
    """
    await asyncio.sleep(300)

    if any(a["id"] == action["id"] for a in orchestrator.admin_handler.approval_queue):
        logger.warning("Escalation: Approval %s timed out. Initiating Voice Call...", action["id"])

        now = datetime.now().hour
        dnd_start = getattr(orchestrator.config.system, "dnd_start", 22)
        dnd_end = getattr(orchestrator.config.system, "dnd_end", 7)

        is_dnd = False
        if dnd_start > dnd_end:
            is_dnd = now >= dnd_start or now < dnd_end
        else:
            is_dnd = dnd_start <= now < dnd_end

        if is_dnd:
            logger.info("Escalation: DND active. Skipping voice call.")
            return

        try:
            events = await orchestrator.adapters["mcp"].call_tool(
                "google-services",
                "list_events",
                {"limit": 3},
            )
            if events and isinstance(events, list):
                for event in events:
                    summary = str(event.get("summary", "")).upper()
                    if any(
                        k in summary
                        for k in [
                            "BUSY",
                            "MEETING",
                            "DND",
                            "SLEEP",
                            "DO NOT DISTURB",
                        ]
                    ):
                        logger.info("Escalation: Dynamic DND active via Calendar ('%s'). Skipping call.", summary)
                        return
        except Exception as e:
            logger.warning("Escalation: Calendar check failed (expected if not configured): %s", e)

        admin_phone = getattr(orchestrator.config.system, "admin_phone", None)
        if admin_phone and orchestrator.adapters["messaging"].voice_adapter:
            script = (
                "Hello, this is Mega Bot. A critical vision approval is pending. "
                "Please check your messages and authorize action."
            )
            await orchestrator.adapters["messaging"].voice_adapter.make_call(
                admin_phone, script, ivr=True, action_id=action["id"]
            )
        else:
            logger.warning("Escalation: No admin phone or voice adapter configured.")


# ------------------------------------------------------------------
# Computer use approval interlock
# ------------------------------------------------------------------


async def handle_computer_tool(
    orchestrator: "MegaBotOrchestrator",
    tool_input: Dict,
    websocket: WebSocket,
    action_id: str,
    callback: Optional[Any] = None,
) -> None:
    """Handle Anthropic Computer Use tool calls with Approval Interlock.

    Queues the action for admin approval and broadcasts the requirement
    to all connected UI clients.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        tool_input: The tool input payload (contains ``action`` key).
        websocket: The WebSocket connection associated with this tool call.
        action_id: The unique tool-use ID from the LLM response.
        callback: Optional callback to invoke when the action is approved/executed.
    """
    action_type = tool_input.get("action")
    description = f"Computer Use: {action_type} ({tool_input})"

    action = {
        "id": action_id or str(uuid.uuid4()),
        "type": "computer_use",
        "payload": tool_input,
        "description": description,
        "websocket": websocket,
        "callback": callback,
    }
    orchestrator.admin_handler.approval_queue.append(action)

    await websocket.send_json({"type": "status", "content": f"Computer action queued for approval: {action_type}"})
    safe_action = _sanitize_action(action)
    for client in list(orchestrator.clients):
        await client.send_json({"type": "approval_required", "action": safe_action})


# ------------------------------------------------------------------
# Identity claim detection
# ------------------------------------------------------------------


async def check_identity_claims(
    orchestrator: "MegaBotOrchestrator",
    content: str,
    platform: str,
    platform_id: str,
    chat_id: str,
) -> None:
    """Analyze message for identity claims and offer to link.

    Uses keyword detection followed by LLM verification to detect when
    a user claims to be a known identity, then queues an approval action
    for account linking.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        content: The message content to analyze.
        platform: The platform the message came from.
        platform_id: The sender's platform-specific ID.
        chat_id: The chat/conversation ID.
    """
    if any(k in content.upper() for k in ["I AM", "IT'S ME", "THIS IS", "MY NAME"]):
        prompt = (
            f"Does the user claim to be someone specific in this message: '{content}'? "
            f"If so, return only the internal name they claim to be. Otherwise return 'NONE'."
        )
        claimed_name = await orchestrator.llm.generate(
            context="Identity Verification",
            messages=[{"role": "user", "content": prompt}],
        )
        claimed_name = str(claimed_name).strip().strip("'\"").upper()

        if "NONE" not in claimed_name:
            logger.info("Identity-Link: Detected claim to be '%s' from %s:%s", claimed_name, platform, platform_id)

            action = {
                "id": str(uuid.uuid4()),
                "type": "identity_link",
                "payload": {
                    "internal_id": claimed_name,
                    "platform": platform,
                    "platform_id": platform_id,
                    "chat_id": chat_id,
                },
                "description": f"Link {platform} ID to identity '{claimed_name}'",
            }
            orchestrator.admin_handler.approval_queue.append(action)

            resp = Message(
                content=(
                    f"I think you are '{claimed_name}'. Link this {platform} account "
                    f"to your unified history? Type `!approve {action['id']}`."
                ),
                sender="System",
            )
            _safe_create_task(orchestrator.send_platform_message(resp, chat_id=chat_id, platform=platform))
