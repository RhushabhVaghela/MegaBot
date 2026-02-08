import json
import logging
from typing import Any

from core.interfaces import Message
from core.task_utils import safe_create_task

logger = logging.getLogger(__name__)


class MessageRouter:
    """Extracted message routing logic for platform delivery.

    This class holds the send_platform_message and _to_platform_message
    logic previously implemented on the orchestrator, but operates using
    the passed orchestrator reference so services are resolved from it.
    """

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def _to_platform_message(self, message: Message, chat_id: str | None = None) -> Any:
        """Convert core Message to PlatformMessage for native messaging"""
        import uuid

        from adapters.messaging import MediaAttachment, MessageType, PlatformMessage

        target_chat = chat_id or message.metadata.get("chat_id", "broadcast")

        platform_attachments = []
        if hasattr(message, "attachments") and message.attachments:
            for att in message.attachments:
                try:
                    # Map 'type' if it's a string to MessageType enum
                    if isinstance(att.get("type"), str):
                        att["type"] = MessageType(att["type"]).value
                    platform_attachments.append(MediaAttachment.from_dict(att))
                except Exception as e:
                    logger.error("Error converting attachment: %s", e)

        return PlatformMessage(
            id=str(uuid.uuid4()),
            platform="native",
            sender_id="megabot-core",
            sender_name=message.sender,
            chat_id=target_chat,
            content=message.content,
            message_type=MessageType.TEXT,
            attachments=platform_attachments,
        )

    async def send_platform_message(
        self,
        message: Message,
        chat_id: str | None = None,
        platform: str = "native",
        target_client: str | None = None,
    ):  # pragma: no cover
        """Send a message to a platform and record it in history.

        Behavior preserved exactly from core.orchestrator.send_platform_message.
        Uses services via self.orchestrator (memory, adapters, permissions, etc.).
        """
        orchestrator = self.orchestrator
        target_chat = chat_id or message.metadata.get("chat_id", "broadcast")

        # Visual Redaction Agent: Detect and blur sensitive areas before sending
        if hasattr(message, "attachments") and message.attachments:
            for att in message.attachments:
                if str(att.get("type")).lower() == "image" and att.get("data"):
                    logger.info("Redaction-Agent: Scanning image for %s...", target_chat)
                    try:
                        # 1. Analyze for sensitive regions
                        analysis_raw = await orchestrator.computer_driver.execute("analyze_image", text=att["data"])
                        analysis = json.loads(analysis_raw)
                        regions = analysis.get("sensitive_regions", [])

                        if regions:
                            logger.info("Redaction-Agent: Blurring %d sensitive areas.", len(regions))
                            redacted_data = await orchestrator.computer_driver.execute(
                                "blur_regions", text=att["data"], regions=regions
                            )

                            # 2. Verify Redaction
                            if await orchestrator._verify_redaction(redacted_data):
                                att["data"] = redacted_data
                                att["metadata"] = att.get("metadata", {})
                                att["metadata"]["redacted"] = True
                            else:
                                logger.warning("Redaction-Agent: Verification FAILED. Blocking image.")
                                att["content"] = "[SECURITY BLOCK: Redaction verification failed]"
                                if "data" in att:
                                    del att["data"]
                        else:
                            # No sensitive regions detected in first pass
                            pass
                    except Exception as e:
                        logger.error("Redaction failed: %s", e)

        # Vision Policy Enforcement: Require approval for outbound images
        has_images = any(str(att.get("type")).lower() == "image" for att in getattr(message, "attachments", []))

        if has_images and platform != "websocket":
            auth = orchestrator.permissions.is_authorized("vision.outbound")
            if auth is False:
                logger.warning("Vision Policy: Outbound image blocked for %s", target_chat)
                return
            if auth is None:
                # If it's already a security message, don't loop
                if message.sender == "Security":
                    pass
                else:
                    logger.info("Vision Policy: Queuing outbound image for approval in %s", target_chat)
                    import uuid

                    action = {
                        "id": str(uuid.uuid4()),
                        "type": "outbound_vision",
                        "payload": {
                            "message_content": message.content,
                            "attachments": message.attachments,
                            "chat_id": target_chat,
                            "platform": platform,
                            "target_client": target_client,
                        },
                        "description": f"Send image to {platform}:{target_chat}",
                    }
                    orchestrator.admin_handler.approval_queue.append(action)

                    # Start Escalation Timer for Voice Call
                    safe_create_task(orchestrator._start_approval_escalation(action))

                    # Notify admins
                    admin_resp = Message(
                        content=f"⚠️ Vision Approval Required: Send image to {target_chat}\nType `!approve {action['id']}` to authorize.",
                        sender="Security",
                    )
                    # Use a background task to avoid recursion depth if send_platform_message is called in a loop
                    safe_create_task(orchestrator.message_router.send_platform_message(admin_resp, platform=platform))
                    return

        # Granular Pruning: Tag architectural decisions to keep forever
        metadata = message.metadata.copy()
        if any(
            keyword in message.content.upper()
            for keyword in [
                "DECISION",
                "ARCHITECT",
                "PATTERN",
                "LEARNED LESSON",
            ]
        ):
            metadata["keep_forever"] = True

        # Record in DB
        await orchestrator.memory.chat_write(
            chat_id=target_chat,
            platform=platform,
            role="assistant",
            content=message.content,
            metadata=metadata,
        )

        # Update cache
        if target_chat in orchestrator.message_handler.chat_contexts:
            orchestrator.message_handler.chat_contexts[target_chat].append(
                {"role": "assistant", "content": message.content}
            )
            orchestrator.message_handler.chat_contexts[target_chat] = orchestrator.message_handler.chat_contexts[
                target_chat
            ][-10:]

        # Route to appropriate adapter
        if platform in [
            "cloudflare",
            "vpn",
            "direct",
            "local",
            "gateway",
        ]:
            if target_client:
                # Send back through Unified Gateway
                msg_payload = {
                    "type": "message",
                    "content": message.content,
                    "sender": message.sender,
                    "metadata": metadata,
                }
                await orchestrator.adapters["gateway"].send_message(target_client, msg_payload)
            else:
                # Broadcast or generic? For now, send to last active client if no target
                if orchestrator.last_active_chat and orchestrator.last_active_chat["platform"] == platform:
                    await orchestrator.adapters["gateway"].send_message(
                        orchestrator.last_active_chat["chat_id"],
                        {"type": "message", "content": message.content},
                    )

        platform_msg = self._to_platform_message(message, chat_id=target_chat)
        platform_msg.platform = platform
        await orchestrator.adapters["messaging"].send_message(platform_msg, target_client=target_client)
