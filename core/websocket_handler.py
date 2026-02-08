"""WebSocket client handler extracted from ``core/orchestrator.py``.

Manages the WebSocket message loop for the MegaBot UI, including message
routing, mode switching, MCP tool calls, memory search, shell command
approval, and action approval/rejection workflows.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional, Any, TYPE_CHECKING

from fastapi import WebSocket  # type: ignore

from core.interfaces import Message
from core.task_utils import safe_create_task as _safe_create_task, sanitize_action

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator

logger = logging.getLogger(__name__)

# Import greeting from shared constants to avoid circular imports
from core.constants import GREETING_TEXT


async def handle_client(orchestrator: "MegaBotOrchestrator", websocket: WebSocket) -> None:
    """Handle a single WebSocket client connection lifecycle.

    Accepts the connection, sends a greeting, then enters a message loop
    that routes incoming messages based on their ``type`` field.

    Args:
        orchestrator: The MegaBotOrchestrator instance.
        websocket: The FastAPI WebSocket connection.
    """
    await websocket.accept()
    orchestrator.clients.add(websocket)

    # Send initial greeting
    await websocket.send_json(
        {
            "type": "message",
            "content": GREETING_TEXT,
            "sender": "MegaBot",
            "timestamp": datetime.now().isoformat(),
        }
    )

    try:
        while True:  # pragma: no cover
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            logger.debug("Received from UI: %s", msg_data)

            msg_type = msg_data.get("type")

            if msg_type == "message":
                await _handle_message(orchestrator, msg_data, websocket)

            elif msg_type == "set_mode":
                orchestrator.mode = msg_data["mode"]
                await websocket.send_json({"type": "mode_updated", "mode": orchestrator.mode})

            elif msg_type == "mcp_call":
                result = await orchestrator.adapters["mcp"].call_tool(
                    msg_data["server"], msg_data["tool"], msg_data["params"]
                )
                await websocket.send_json({"type": "mcp_result", "result": result})

            elif msg_type == "search":
                results = await orchestrator.adapters["memu"].search(msg_data["query"])
                await websocket.send_json({"type": "search_results", "results": results})

            elif msg_type == "command":
                await _handle_command(orchestrator, msg_data, websocket)

            elif msg_type == "approve_action":
                action_id = msg_data.get("action_id")
                await orchestrator._process_approval(action_id, approved=True)

            elif msg_type == "reject_action":
                action_id = msg_data.get("action_id")
                await orchestrator._process_approval(action_id, approved=False)

    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        orchestrator.clients.discard(websocket)


async def _handle_message(
    orchestrator: "MegaBotOrchestrator",
    msg_data: Dict[str, Any],
    websocket: WebSocket,
) -> None:
    """Process an incoming 'message' type WebSocket payload."""
    message = Message(content=msg_data["content"], sender="user")
    # Store in memU
    await orchestrator.adapters["memu"].store(f"user_msg_{id(message)}", message.content)

    if orchestrator.mode == "build":
        _safe_create_task(orchestrator.run_autonomous_build(message, websocket))
    else:
        # Standard relay to OpenClaw
        await orchestrator.adapters["openclaw"].send_message(message)


async def _handle_command(
    orchestrator: "MegaBotOrchestrator",
    msg_data: Dict[str, Any],
    websocket: WebSocket,
) -> None:
    """Queue a shell command for approval."""
    import uuid

    cmd = msg_data.get("command")
    action = {
        "id": str(uuid.uuid4()),
        "type": "system_command",
        "payload": {"method": "system.run", "params": {"command": cmd}},
        "description": f"Terminal Execute: {cmd}",
        "websocket": websocket,
    }
    orchestrator.admin_handler.approval_queue.append(action)
    await websocket.send_json(
        {
            "type": "status",
            "content": f"Command queued for approval: {cmd}",
        }
    )
    # Broadcast update to all connected clients
    safe_action = sanitize_action(action)
    for client in list(orchestrator.clients):
        await client.send_json({"type": "approval_required", "action": safe_action})
