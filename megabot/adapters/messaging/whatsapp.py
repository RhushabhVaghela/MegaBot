import asyncio
import logging
import uuid
from typing import Any

from megabot.core.resource_guard import LRUCache

from .server import MessageType, PlatformAdapter, PlatformMessage

logger = logging.getLogger(__name__)


class WhatsAppAdapter(PlatformAdapter):
    """
    WhatsApp adapter using OpenClaw for WhatsApp Web integration.
    Falls back to WhatsApp Business API if OpenClaw is not available.
    """

    GRAPH_API_VERSION = "v17.0"
    GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

    def __init__(self, platform_name: str, server: Any, config: dict[str, Any] | None = None):
        super().__init__(platform_name, server)
        self.config = config or {}
        self.phone_number_id = self.config.get("phone_number_id", "")
        self.access_token = self.config.get("access_token", "")
        self.push_notifications_enabled = self.config.get("push_notifications", {}).get("enabled", True)
        self.session = None
        self.message_cache: LRUCache[str, Any] = LRUCache(maxsize=1024)
        self.group_chats: LRUCache[str, Any] = LRUCache(maxsize=256)
        self.notification_callbacks = []
        self._pending_notifications: LRUCache[str, Any] = LRUCache(maxsize=256)
        self.is_initialized = False
        self.retry_attempts = 3
        self._openclaw = None
        self._use_openclaw = False

    async def initialize(self) -> bool:
        """Initialize the WhatsApp adapter with OpenClaw as primary method."""
        try:
            # Try to initialize OpenClaw first
            await self._init_openclaw()
            if self._use_openclaw:
                self.is_initialized = True
                return True

            # Fallback to direct WhatsApp Business API
            await self._init_direct_api()
            return self.is_initialized
        except Exception as e:
            logger.error("Initialization failed: %s", e)
            return False

    async def _init_openclaw(self) -> bool:
        """Initialize OpenClaw connection for WhatsApp Web."""
        try:
            # Check if OpenClaw is available through the server
            if hasattr(self.server, "openclaw") and self.server.openclaw:
                self._openclaw = self.server.openclaw
                self._use_openclaw = True
                logger.info("Using OpenClaw for WhatsApp Web integration")
                return True

            # Try to import and create OpenClaw adapter
            from ..openclaw_adapter import OpenClawAdapter

            openclaw_config = self.config.get("openclaw", {})
            host = openclaw_config.get("host", "localhost")
            port = openclaw_config.get("port", 8080)
            auth_token = openclaw_config.get("auth_token") or self.access_token

            self._openclaw = OpenClawAdapter(host=host, port=port, auth_token=auth_token)
            await self._openclaw.connect()
            self._use_openclaw = True
            logger.info("Connected to OpenClaw for WhatsApp Web")
            return True
        except Exception as e:
            logger.warning("OpenClaw not available: %s", e)
            self._use_openclaw = False
            return False

    async def _init_direct_api(self) -> bool:
        """Initialize direct WhatsApp Business API connection."""
        try:
            import aiohttp

            self.session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.access_token}"})
            if not self.phone_number_id:
                logger.warning("No phone_number_id configured")
                return False

            async with self.session.get(f"{self.GRAPH_API_BASE}/{self.phone_number_id}") as resp:
                if resp.status == 200:
                    self.is_initialized = True
                    logger.info("Connected via Business API")
                    return True
                else:
                    logger.error("Business API auth failed: %s", resp.status)
                    return False
        except Exception as e:
            logger.error("Direct API initialization failed: %s", e)
            return False

    def register_notification_callback(self, callback):
        self.notification_callbacks.append(callback)

    async def _notify_callbacks(self, data):
        for cb in self.notification_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.warning("Notification callback error: %s", e)

    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_to: str | None = None,
        markup: bool = False,
        preview_url: bool = True,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send text message via OpenClaw or Business API."""
        try:
            content = self._format_text(text, markup=markup)
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"

            # Try OpenClaw first
            if self._use_openclaw and self._openclaw:
                result = await self._send_via_openclaw(chat_id, content, "text")
                if result:
                    return result

            # Fallback to direct API
            if self.is_initialized and self.session:
                res = await self._send_with_retry(
                    {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "text": {"body": content, "preview_url": preview_url},
                    }
                )
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=content,
                reply_to=reply_to,
            )
        except Exception as e:
            logger.error("send_text error: %s", e)
            return None

    async def send_media(
        self,
        chat_id: str,
        media_path: str,
        caption: str | None = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send media message via OpenClaw or Business API."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"

            # Try OpenClaw first for local file handling
            if self._use_openclaw and self._openclaw:
                result = await self._send_media_via_openclaw(chat_id, media_path, caption, media_type)
                if result:
                    return result

            # Fallback to direct API - requires media upload first
            if self.is_initialized and self.session:
                media_id = await self._upload_media(media_path, media_type)
                if media_id:
                    media_type_str = self._map_media_type(media_type)
                    res = await self._send_with_retry(
                        {
                            "messaging_product": "whatsapp",
                            "to": chat_id,
                            "type": media_type_str,
                            media_type_str: {
                                "id": media_id,
                                "caption": caption or "",
                            },
                        }
                    )
                    if res:
                        msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                    else:
                        return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=caption or "",
                message_type=media_type,
                metadata={"media_path": media_path},
            )
        except Exception as e:
            logger.error("send_media error: %s", e)
            return None

    async def send_document(
        self, chat_id: str, document_path: str, caption: str | None = None
    ) -> PlatformMessage | None:  # pragma: no cover
        return await self.send_media(chat_id, document_path, caption, MessageType.DOCUMENT)

    async def send_location(
        self, chat_id: str, latitude: float, longitude: float, **kwargs
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send location message."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"
            address = kwargs.get("address", "")
            name = kwargs.get("name", "Location")

            if self._use_openclaw and self._openclaw:
                # Use OpenClaw for location sharing
                result = await self._openclaw.execute_tool(
                    "whatsapp.send_location",
                    {
                        "chat_id": chat_id,
                        "latitude": latitude,
                        "longitude": longitude,
                        "address": address,
                        "name": name,
                    },
                )
                if result and not result.get("error"):
                    msg_id = result.get("result", {}).get("message_id", msg_id)
            elif self.is_initialized and self.session:
                res = await self._send_with_retry(
                    {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "location",
                        "location": {
                            "latitude": latitude,
                            "longitude": longitude,
                            "name": name,
                            "address": address,
                        },
                    }
                )
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=f"Location: {latitude}, {longitude}",
                message_type=MessageType.LOCATION,
                metadata={
                    "lat": latitude,
                    "long": longitude,
                    "address": address,
                    "name": name,
                },
            )
        except Exception as e:
            logger.error("send_location error: %s", e)
            return None

    async def send_contact(
        self, chat_id: str, contact_info: dict[str, Any]
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send contact card."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"
            name = contact_info.get("name", "")
            phone = contact_info.get("phone", "")

            if self.is_initialized and self.session:
                res = await self._send_with_retry(
                    {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "contacts",
                        "contacts": [
                            {
                                "name": {
                                    "formatted_name": name,
                                    "first_name": name.split()[0] if name else "",
                                },
                                "phones": [{"phone": phone, "type": "MOBILE"}],
                            }
                        ],
                    }
                )
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=f"Contact: {name}",
                message_type=MessageType.CONTACT,
                metadata={"contact_name": name, "contact_phone": phone},
            )
        except Exception as e:
            logger.error("send_contact error: %s", e)
            return None

    async def send_template(
        self, chat_id: str, template_name: str, **kwargs
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send template message."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"
            language = kwargs.get("language", "en")
            components = kwargs.get("components", [])

            if self.is_initialized and self.session:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": language},
                    },
                }
                if components:
                    payload["template"]["components"] = components

                res = await self._send_with_retry(payload)
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=f"Template: {template_name}",
                metadata={"template_name": template_name, "language": language},
            )
        except Exception as e:
            logger.error("send_template error: %s", e)
            return None

    async def send_push_notification(
        self,
        chat_id: str,
        title: str,
        body: str,
        buttons: list[dict[str, str]] | None = None,
        **kwargs,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send interactive message with notification styling."""
        try:
            # Create a formatted message with notification styling
            content = f"*{title}*\n\n{body}"
            if buttons:
                button_text = "\n".join([f"• {btn.get('title', '')}" for btn in buttons])
                content += f"\n\n{button_text}"

            # Try to send via OpenClaw first
            result = await self._send_via_openclaw(chat_id, content, "text")
            if result:
                # Preserve original metadata including buttons
                result.metadata["notification_type"] = "push"
                result.metadata["buttons"] = buttons or []
                result.metadata["title"] = title
                result.metadata["body"] = body
                result.metadata["notification_id"] = str(uuid.uuid4())
                return result

            # Fallback to regular send_text
            result = await self.send_text(chat_id, content)
            if result:
                result.metadata["notification_type"] = "push"
                result.metadata["buttons"] = buttons or []
                result.metadata["notification_id"] = str(uuid.uuid4())
            return result
        except Exception as e:
            logger.error("send_push_notification error: %s", e)
            return None

    async def send_interactive_list(
        self,
        chat_id: str,
        header: str,
        body: str,
        button_text: str,
        sections: list[dict[str, Any]],
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send interactive list message."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"

            if self.is_initialized and self.session:
                res = await self._send_with_retry(
                    {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "interactive",
                        "interactive": {
                            "type": "list",
                            "header": {"type": "text", "text": header},
                            "body": {"text": body},
                            "action": {
                                "button": button_text,
                                "sections": sections,
                            },
                        },
                    }
                )
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=f"{header}: {body}",
                metadata={"interactive_type": "list", "sections": sections},
            )
        except Exception as e:
            logger.error("send_interactive_list error: %s", e)
            return None

    async def send_reply_buttons(
        self, chat_id: str, text: str, buttons: list[dict[str, str]], **kwargs
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send reply buttons message."""
        try:
            msg_id = f"wa_{uuid.uuid4().hex[:16]}"

            if self.is_initialized and self.session:
                res = await self._send_with_retry(
                    {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": text},
                            "action": {
                                "buttons": [
                                    {
                                        "type": "reply",
                                        "reply": {
                                            "id": btn["id"],
                                            "title": btn["title"],
                                        },
                                    }
                                    for btn in buttons
                                ]
                            },
                        },
                    }
                )
                if res:
                    msg_id = res.get("messages", [{}])[0].get("id", msg_id)
                else:
                    return None

            return PlatformMessage(
                id=msg_id,
                platform="whatsapp",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=text,
                metadata={"interactive_type": "button", "buttons": buttons},
            )
        except Exception as e:
            logger.error("send_reply_buttons error: %s", e)
            return None

    async def send_order_notification(
        self,
        chat_id: str,
        order_id: str,
        order_status: str,
        items: list[dict[str, Any]],
        total: str,
        **kwargs,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send order notification."""
        try:
            status_emoji = {
                "confirmed": "✅",
                "processing": "⚙️",
                "shipped": "📦",
                "out_for_delivery": "🚚",
                "delivered": "🎉",
                "cancelled": "❌",
            }.get(order_status.lower(), "📋")

            items_text = "\n".join([f"• {item.get('name', '')} x{item.get('quantity', 1)}" for item in items])
            content = (
                f"{status_emoji} *Order Update*\n\n"
                f"Order #{order_id}\n"
                f"Status: {order_status.title()}\n\n"
                f"*Items:*\n{items_text}\n\n"
                f"*Total:* {total}"
            )

            buttons = [{"id": "view_order", "title": "View Order"}]
            if kwargs.get("action_url"):
                buttons.append({"id": "track", "title": "Track"})

            return await self.send_reply_buttons(chat_id, content, buttons)
        except Exception as e:
            logger.error("send_order_notification error: %s", e)
            return None

    async def send_payment_notification(
        self,
        chat_id: str,
        payment_id: str,
        amount: str,
        currency: str,
        status: str,
        description: str,
        **kwargs,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send payment notification."""
        try:
            config = {
                "success": {"emoji": "✅", "title": "Payment Received"},
                "pending": {"emoji": "⏳", "title": "Payment Pending"},
                "failed": {"emoji": "❌", "title": "Payment Failed"},
                "refunded": {"emoji": "↩️", "title": "Payment Refunded"},
            }.get(status.lower(), {"emoji": "💰", "title": "Payment Update"})

            content = (
                f"{config['emoji']} *{config['title']}*\n\n"
                f"Payment ID: {payment_id}\n"
                f"Amount: {amount} {currency}\n"
                f"Status: {status.title()}\n"
                f"Description: {description}"
            )

            return await self.send_text(chat_id, content)
        except Exception as e:
            logger.error("send_payment_notification error: %s", e)
            return None

    async def send_appointment_reminder(
        self,
        chat_id: str,
        appointment_id: str,
        service_name: str,
        datetime_str: str,
        location: str | None = None,
        provider_name: str | None = None,
        confirmation_buttons: bool = False,
        **kwargs,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send appointment reminder."""
        try:
            content = f"📅 *Appointment Reminder*\n\nService: {service_name}\nDate/Time: {datetime_str}"
            if provider_name:
                content += f"\nProvider: {provider_name}"
            if location:
                content += f"\nLocation: {location}"

            if confirmation_buttons:
                buttons = [
                    {"id": "confirm", "title": "Confirm"},
                    {"id": "reschedule", "title": "Reschedule"},
                    {"id": "cancel", "title": "Cancel"},
                ]
                return await self.send_reply_buttons(chat_id, content, buttons)
            else:
                return await self.send_text(chat_id, content)
        except Exception as e:
            logger.error("send_appointment_reminder error: %s", e)
            return None

    async def create_group(self, group_name: str, participants: list[str]) -> str | None:
        """Create a WhatsApp group. Note: Requires WhatsApp Business API with appropriate permissions."""
        try:
            if self._use_openclaw and self._openclaw:
                result = await self._openclaw.execute_tool(
                    "whatsapp.create_group",
                    {"group_name": group_name, "participants": participants},
                )
                if result and not result.get("error"):
                    return result.get("result", {}).get("group_id")

            # Fallback: create local group tracking
            gid = f"group_{uuid.uuid4().hex[:16]}"
            self.group_chats[gid] = {"name": group_name, "participants": participants}
            return gid
        except Exception as e:
            logger.error("create_group error: %s", e)
            return None

    async def add_group_participant(self, group_id: str, phone: str) -> bool:
        """Add participant to group."""
        try:
            if group_id in self.group_chats:
                if phone not in self.group_chats[group_id]["participants"]:
                    self.group_chats[group_id]["participants"].append(phone)
                return True
            return False
        except (KeyError, TypeError):
            return False

    async def get_message_status(self, msg_id: str) -> dict | None:
        """Get message delivery status."""
        try:
            if self.is_initialized and self.session:
                async with self.session.get(f"{self.GRAPH_API_BASE}/{msg_id}") as resp:
                    if resp.status == 200:
                        return await resp.json()
            return {"status": "sent"}
        except Exception:
            return {"status": "unknown"}

    async def handle_webhook(self, data: dict) -> PlatformMessage | None:
        """Handle incoming webhook from WhatsApp."""
        if not data or not data.get("entry"):
            return None
        try:
            val = data["entry"][0]["changes"][0]["value"]
            if "statuses" in val:
                await self._notify_callbacks(val["statuses"][0])
                return None
            msg_data = val.get("messages", [{}])[0]
            if not msg_data.get("id"):
                return None
            if msg_data.get("type") == "interactive":
                await self._notify_callbacks(msg_data)
                # Handle interactive responses (button clicks, etc.)
                interactive_data = msg_data.get("interactive", {})
                content = ""
                if interactive_data.get("type") == "button_reply":
                    content = interactive_data.get("button_reply", {}).get("title", "")
                elif interactive_data.get("type") == "list_reply":
                    content = interactive_data.get("list_reply", {}).get("title", "")

                if not content:
                    return None

                return PlatformMessage(
                    id=msg_data["id"],
                    platform="whatsapp",
                    sender_id=msg_data.get("from", ""),
                    sender_name="User",
                    chat_id=msg_data.get("from", ""),
                    content=content,
                    message_type=MessageType.TEXT,
                    metadata={"raw": msg_data},
                )

            # Extract content based on message type
            content = ""
            msg_type = msg_data.get("type", "text")
            if msg_type == "text":
                content = msg_data.get("text", {}).get("body", "")
            elif msg_type == "image":
                content = "[Image]"
            elif msg_type == "video":
                content = "[Video]"
            elif msg_type == "audio":
                content = "[Audio]"
            elif msg_type == "document":
                content = f"[Document: {msg_data.get('document', {}).get('filename', '')}]"
            elif msg_type == "location":
                loc = msg_data.get("location", {})
                content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
            elif msg_type == "contacts":
                content = "[Contact]"

            return PlatformMessage(
                id=msg_data["id"],
                platform="whatsapp",
                sender_id=msg_data.get("from", ""),
                sender_name="User",
                chat_id=msg_data.get("from", ""),
                content=content,
                message_type=getattr(MessageType, msg_type.upper(), MessageType.TEXT),
                metadata={"raw": msg_data},
            )
        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.error("handle_webhook error: %s", e)
            return None

    async def _send_with_retry(self, payload: dict) -> dict | None:
        """Send message with retry logic for direct API."""
        if not self.session:
            return None
        for attempt in range(self.retry_attempts):
            try:
                async with self.session.post(
                    f"{self.GRAPH_API_BASE}/{self.phone_number_id}/messages",
                    json=payload,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 429 or resp.status >= 500:  # Rate limited or Server Error
                        wait_time = 0.01 * (2**attempt)
                        await asyncio.sleep(wait_time)
                        continue
                    error_text = await resp.text()
                    logger.error("API error %s: %s", resp.status, error_text)
                    return None
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    logger.error("Send failed after %d attempts: %s", self.retry_attempts, e)
                    return None
                await asyncio.sleep(0.01 * (2**attempt))
        return None

    async def _send_via_openclaw(
        self, chat_id: str, content: str, msg_type: str
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send message via OpenClaw (WhatsApp Web)."""
        try:
            if not self._openclaw:
                return None

            result = await self._openclaw.execute_tool(
                "whatsapp.send_message",
                {"chat_id": chat_id, "content": content, "type": msg_type},
            )

            if result and not result.get("error"):
                msg_id = result.get("result", {}).get("message_id", f"oc_{uuid.uuid4().hex}")
                return PlatformMessage(
                    id=msg_id,
                    platform="whatsapp",
                    sender_id="megabot",
                    sender_name="MegaBot",
                    chat_id=chat_id,
                    content=content,
                    metadata={"source": "openclaw", "type": msg_type},
                )
            return None
        except Exception as e:
            logger.error("OpenClaw send error: %s", e)
            return None

    async def _send_media_via_openclaw(
        self,
        chat_id: str,
        media_path: str,
        caption: str | None,
        media_type: MessageType,
    ) -> PlatformMessage | None:  # pragma: no cover
        """Send media via OpenClaw."""
        try:
            if not self._openclaw:
                return None

            result = await self._openclaw.execute_tool(
                "whatsapp.send_media",
                {
                    "chat_id": chat_id,
                    "media_path": media_path,
                    "caption": caption or "",
                    "media_type": self._map_media_type(media_type),
                },
            )

            if result and not result.get("error"):
                msg_id = result.get("result", {}).get("message_id", f"oc_{uuid.uuid4().hex}")
                return PlatformMessage(
                    id=msg_id,
                    platform="whatsapp",
                    sender_id="megabot",
                    sender_name="MegaBot",
                    chat_id=chat_id,
                    content=caption or "",
                    message_type=media_type,
                    metadata={"source": "openclaw", "media_path": media_path},
                )
            return None
        except Exception as e:
            logger.error("OpenClaw media send error: %s", e)
            return None

    async def _upload_media(self, file_path: str, media_type: MessageType) -> str | None:
        """Upload media to WhatsApp servers."""
        if not self.session:
            return None
        try:
            import mimetypes
            import os

            import aiohttp

            if not os.path.exists(file_path):
                logger.error("Media file not found: %s", file_path)
                return None

            mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

            data = aiohttp.FormData()
            data.add_field("messaging_product", "whatsapp")
            data.add_field("type", self._map_media_type(media_type))

            with open(file_path, "rb") as f:
                file_content = f.read()

            data.add_field(
                "file",
                file_content,
                filename=file_path.split("/")[-1],
                content_type=mime_type,
            )

            async with self.session.post(
                f"{self.GRAPH_API_BASE}/{self.phone_number_id}/media",
                data=data,
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("id")
                else:
                    error_text = await resp.text()
                    logger.error("Media upload failed: %s - %s", resp.status, error_text)
                    return None
        except Exception as e:
            logger.error("Media upload error: %s", e)
            return None

    async def shutdown(self):
        """Clean shutdown of WhatsApp adapter."""
        try:
            if self.session:
                await self.session.close()
                logger.info("HTTP session closed")
            if self._openclaw:
                # OpenClaw doesn't have explicit disconnect, but we could add one
                logger.info("OpenClaw adapter closed")
            logger.info("Adapter shutdown complete")
        except Exception as e:
            logger.error("Error during shutdown: %s", e)

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number format."""
        # Remove spaces, dashes, and parentheses
        normalized = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        # Ensure it starts with +
        if not normalized.startswith("+"):
            normalized = "+" + normalized
        return normalized

    def _format_text(self, text: str, **kwargs) -> str:
        """Format text for WhatsApp."""
        if kwargs.get("markup"):
            # Escape special characters if markup is enabled
            text = text.replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")
        return text

    async def make_call(self, chat_id: str, is_video: bool = False) -> bool:
        """Voice/Video calls are not supported via Business API."""
        logger.warning("Voice/Video calls not supported via WhatsApp Business API")
        return False

    def _get_contact_name(self, phone: str) -> str:
        """Get contact name from phone number."""
        return f"WhatsApp:{phone}"

    def _map_media_type(self, msg_type: MessageType) -> str:
        """Map MessageType to WhatsApp media type."""
        mapping = {
            MessageType.IMAGE: "image",
            MessageType.VIDEO: "video",
            MessageType.AUDIO: "audio",
            MessageType.DOCUMENT: "document",
            MessageType.STICKER: "sticker",
        }
        return mapping.get(msg_type, "document")

    def _mime_to_message_type(self, mime: str) -> MessageType:
        """Convert MIME type to MessageType."""
        if "image" in mime:
            return MessageType.IMAGE
        if "video" in mime:
            return MessageType.VIDEO
        if "audio" in mime:
            return MessageType.AUDIO
        return MessageType.DOCUMENT

    def _detect_mime_type(self, file_path: str) -> str:
        """Detect MIME type from file path."""
        import mimetypes

        return mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    def _get_mime_type(self, file_path: str, msg_type: MessageType) -> str:
        """Get MIME type for a file, falling back to message type defaults."""
        detected = self._detect_mime_type(file_path)
        if detected != "application/octet-stream":
            return detected

        defaults = {
            MessageType.IMAGE: "image/jpeg",
            MessageType.VIDEO: "video/mp4",
            MessageType.AUDIO: "audio/mpeg",
            MessageType.DOCUMENT: "application/pdf",
        }
        return defaults.get(msg_type, detected)
