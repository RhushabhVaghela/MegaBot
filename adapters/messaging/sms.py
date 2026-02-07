import uuid
import asyncio
import logging
from typing import Any, Dict, Optional
from .server import PlatformAdapter, PlatformMessage, MessageType

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


class SMSAdapter(PlatformAdapter):
    def __init__(self, platform: str, server: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(platform, server)
        self.config = config or {}
        self.account_sid = self.config.get("twilio_account_sid")
        self.auth_token = self.config.get("twilio_auth_token")
        self.from_number = self.config.get("twilio_from_number")
        self.client = None

    async def initialize(self) -> bool:
        if not self.account_sid or not self.auth_token:
            logger.error("[SMS] Missing Twilio credentials")
            return False
        try:
            from twilio.rest import Client

            self.client = Client(self.account_sid, self.auth_token)
            logger.info("[SMS] Twilio client initialized")
            return True
        except Exception as e:
            logger.error("[SMS] Initialization failed: %s", e)
            return False

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> Optional[PlatformMessage]:
        """Send an SMS with retry + exponential backoff."""
        if not self.client or not self.from_number:
            logger.error("[SMS] Client not initialized or missing from_number")
            return None

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                loop = asyncio.get_running_loop()
                message = await loop.run_in_executor(
                    None,
                    lambda: self.client.messages.create(body=text, from_=self.from_number, to=chat_id),
                )
                return PlatformMessage(
                    id=message.sid,
                    platform="sms",
                    sender_id="megabot",
                    sender_name="MegaBot",
                    chat_id=chat_id,
                    content=text,
                    reply_to=reply_to,
                )
            except Exception as e:
                last_error = e
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "[SMS] Send failed (%s), retrying in %.1fs (attempt %d/%d)",
                    e,
                    delay,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(delay)

        logger.error("[SMS] All %d retries exhausted: %s", MAX_RETRIES, last_error)
        return None

    async def send_media(
        self,
        chat_id: str,
        media_url: str,
        caption: Optional[str] = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> Optional[PlatformMessage]:
        """Send an MMS with a media URL. Twilio requires a publicly accessible URL."""
        if not self.client or not self.from_number:
            logger.error("[SMS] Client not initialized or missing from_number")
            return None

        body = caption or ""
        try:
            loop = asyncio.get_running_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    body=body,
                    from_=self.from_number,
                    to=chat_id,
                    media_url=[media_url],
                ),
            )
            return PlatformMessage(
                id=message.sid,
                platform="sms",
                sender_id="megabot",
                sender_name="MegaBot",
                chat_id=chat_id,
                content=body,
                message_type=media_type,
            )
        except Exception as e:
            logger.error("[SMS] MMS send failed: %s", e)
            return None

    async def handle_webhook(self, data: Dict) -> Optional[PlatformMessage]:
        """Parse an incoming Twilio SMS/MMS webhook.

        Twilio sends form-encoded POST data with keys like:
        - MessageSid, From, To, Body
        - NumMedia, MediaUrl0, MediaContentType0 (for MMS)
        """
        if not data:
            return None

        msg_sid = data.get("MessageSid")
        if not msg_sid:
            return None

        sender = data.get("From", "")
        body = data.get("Body", "")

        # Determine message type from media attachments
        message_type = MessageType.TEXT
        num_media = int(data.get("NumMedia", 0))
        if num_media > 0:
            content_type = data.get("MediaContentType0", "")
            if content_type.startswith("image/"):
                message_type = MessageType.IMAGE
            elif content_type.startswith("video/"):
                message_type = MessageType.VIDEO
            elif content_type.startswith("audio/"):
                message_type = MessageType.AUDIO
            else:
                message_type = MessageType.DOCUMENT

            media_url = data.get("MediaUrl0", "")
            if not body:
                body = f"[Media: {media_url}]"

        return PlatformMessage(
            id=msg_sid,
            platform="sms",
            sender_id=sender,
            sender_name=sender,
            chat_id=sender,
            content=body,
            message_type=message_type,
        )

    async def shutdown(self):
        logger.info("[SMS] Adapter shutdown")
