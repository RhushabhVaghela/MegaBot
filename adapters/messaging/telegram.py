import asyncio
import logging
import uuid
from typing import Any

import aiohttp

from .server import MessageType, PlatformAdapter, PlatformMessage

logger = logging.getLogger(__name__)

# Map MessageType to Telegram API method names
_MEDIA_METHOD: dict[MessageType, str] = {
    MessageType.IMAGE: "sendPhoto",
    MessageType.VIDEO: "sendVideo",
    MessageType.AUDIO: "sendAudio",
    MessageType.DOCUMENT: "sendDocument",
    MessageType.STICKER: "sendSticker",
}

_MEDIA_FIELD: dict[MessageType, str] = {
    MessageType.IMAGE: "photo",
    MessageType.VIDEO: "video",
    MessageType.AUDIO: "audio",
    MessageType.DOCUMENT: "document",
    MessageType.STICKER: "sticker",
}

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds


class TelegramAdapter(PlatformAdapter):
    def __init__(self, bot_token: str, server: Any):
        super().__init__("telegram", server)
        self.bot_token = bot_token
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.session = None

    async def _ensure_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def _make_request(self, method: str, data: dict | None = None, retries: int = MAX_RETRIES) -> Any:
        """Make a request to the Telegram Bot API with exponential backoff retry."""
        await self._ensure_session()

        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                async with self.session.post(f"{self.api_url}/{method}", json=data) as resp:
                    result = await resp.json()
                    if resp.status == 200 and result.get("ok"):
                        return result.get("result")
                    # Rate limited — respect Retry-After header
                    if resp.status == 429:
                        retry_after = result.get("parameters", {}).get("retry_after", 5)
                        logger.warning(
                            "[Telegram] Rate limited, retrying after %ds (attempt %d/%d)",
                            retry_after,
                            attempt + 1,
                            retries,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    # Non-retryable API error
                    desc = result.get("description", "Unknown error")
                    logger.error("[Telegram] API error %d: %s", resp.status, desc)
                    return None
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "[Telegram] Request failed (%s), retrying in %.1fs (attempt %d/%d)",
                    exc,
                    delay,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)

        logger.error("[Telegram] All %d retries exhausted: %s", retries, last_error)
        return None

    async def _upload_media(
        self,
        method: str,
        chat_id: str,
        field_name: str,
        file_path: str,
        caption: str | None = None,
    ) -> Any:
        """Upload a local file to Telegram using multipart form data."""
        await self._ensure_session()
        fh = None
        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", chat_id)
            if caption:
                data.add_field("caption", caption)
            fh = open(file_path, "rb")  # noqa: SIM115
            data.add_field(field_name, fh, filename=file_path.split("/")[-1])

            async with self.session.post(f"{self.api_url}/{method}", data=data) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("ok"):
                    return result.get("result")
                logger.error("[Telegram] Upload error: %s", result.get("description"))
                return None
        except Exception as exc:
            logger.error("[Telegram] Upload failed: %s", exc)
            return None
        finally:
            if fh is not None:
                fh.close()

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> PlatformMessage | None:
        res = await self._make_request("sendMessage", {"chat_id": chat_id, "text": text})
        return PlatformMessage(
            id=str(res.get("message_id") if res else uuid.uuid4()),
            platform="telegram",
            sender_id="megabot",
            sender_name="MegaBot",
            chat_id=chat_id,
            content=text,
            reply_to=reply_to,
        )

    async def send_media(
        self,
        chat_id: str,
        media_path: str,
        caption: str | None = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> PlatformMessage | None:
        """Send a media file (image, video, audio, document) to a Telegram chat."""
        method = _MEDIA_METHOD.get(media_type, "sendDocument")
        field = _MEDIA_FIELD.get(media_type, "document")

        # If media_path looks like a URL, send via JSON (Telegram downloads it)
        if media_path.startswith("http://") or media_path.startswith("https://"):
            payload: dict[str, Any] = {"chat_id": chat_id, field: media_path}
            if caption:
                payload["caption"] = caption
            res = await self._make_request(method, payload)
        else:
            # Upload local file via multipart
            res = await self._upload_media(method, chat_id, field, media_path, caption)

        msg_id = str(res.get("message_id")) if res else str(uuid.uuid4())
        return PlatformMessage(
            id=msg_id,
            platform="telegram",
            sender_id="megabot",
            sender_name="MegaBot",
            chat_id=chat_id,
            content=caption or "",
            message_type=media_type,
        )

    async def send_photo(self, chat_id: str, photo: str, **kwargs):
        return await self._make_request("sendPhoto", {"chat_id": chat_id, "photo": photo, **kwargs})

    async def send_document(self, chat_id: str, document_path: str, caption: str | None = None, **kwargs):
        payload: dict[str, Any] = {"chat_id": chat_id, "document": document_path}
        if caption:
            payload["caption"] = caption
        payload.update(kwargs)
        return await self._make_request("sendDocument", payload)

    async def send_contact(self, chat_id: str, phone_number: str, first_name: str, **kwargs):
        return await self._make_request(
            "sendContact",
            {
                "chat_id": chat_id,
                "phone_number": phone_number,
                "first_name": first_name,
                **kwargs,
            },
        )

    async def send_poll(self, chat_id: str, question: str, options: list[str], **kwargs):
        return await self._make_request(
            "sendPoll",
            {"chat_id": chat_id, "question": question, "options": options, **kwargs},
        )

    async def edit_message_text(self, chat_id: str, message_id: int, text: str, **kwargs):
        return await self._make_request(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text, **kwargs},
        )

    async def delete_message(self, chat_id: str, message_id: int):
        return bool(await self._make_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id}))

    async def answer_callback_query(self, callback_query_id: str, **kwargs):
        return bool(
            await self._make_request(
                "answerCallbackQuery",
                {"callback_query_id": callback_query_id, **kwargs},
            )
        )

    async def create_chat_invite_link(self, chat_id: str, **kwargs):
        return await self._make_request("createChatInviteLink", {"chat_id": chat_id, **kwargs})

    async def export_chat_invite_link(self, chat_id: str):
        return await self._make_request("exportChatInviteLink", {"chat_id": chat_id})

    async def get_chat(self, chat_id: str):
        return await self._make_request("getChat", {"chat_id": chat_id})

    async def get_chat_administrators(self, chat_id: str):
        return await self._make_request("getChatAdministrators", {"chat_id": chat_id}) or []

    async def get_chat_members_count(self, chat_id: str):
        return await self._make_request("getChatMembersCount", {"chat_id": chat_id}) or 0

    async def get_chat_member(self, chat_id: str, user_id: int):
        return await self._make_request("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def ban_chat_member(self, chat_id: str, user_id: int, **kwargs):
        return bool(await self._make_request("banChatMember", {"chat_id": chat_id, "user_id": user_id, **kwargs}))

    async def unban_chat_member(self, chat_id: str, user_id: int, **kwargs):
        return bool(await self._make_request("unbanChatMember", {"chat_id": chat_id, "user_id": user_id, **kwargs}))

    async def restrict_chat_member(self, chat_id: str, user_id: int, permissions: dict, **kwargs):
        return bool(
            await self._make_request(
                "restrictChatMember",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "permissions": permissions,
                    **kwargs,
                },
            )
        )

    async def promote_chat_member(self, chat_id: str, user_id: int, **kwargs):
        return bool(await self._make_request("promoteChatMember", {"chat_id": chat_id, "user_id": user_id, **kwargs}))

    async def pin_chat_message(self, chat_id: str, message_id: int, **kwargs):
        return bool(
            await self._make_request(
                "pinChatMessage",
                {"chat_id": chat_id, "message_id": message_id, **kwargs},
            )
        )

    async def unpin_chat_message(self, chat_id: str, **kwargs):
        return bool(await self._make_request("unpinChatMessage", {"chat_id": chat_id, **kwargs}))

    async def leave_chat(self, chat_id: str):
        return bool(await self._make_request("leaveChat", {"chat_id": chat_id}))

    async def forward_message(self, chat_id: str, from_chat_id: str, message_id: int, **kwargs):
        return await self._make_request(
            "forwardMessage",
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
                **kwargs,
            },
        )

    async def get_me(self):
        try:
            return await self._make_request("getMe")
        except Exception:
            return None

    async def get_updates(self, **kwargs):
        try:
            return await self._make_request("getUpdates", kwargs) or []
        except Exception:
            return []

    async def delete_webhook(self):
        try:
            return bool(await self._make_request("deleteWebhook"))
        except Exception:
            return False

    async def handle_webhook(self, data: dict) -> PlatformMessage | None:
        """Parse incoming Telegram update into a PlatformMessage.

        Handles text messages, photos, videos, audio, voice, documents,
        locations, contacts, and callback queries.
        """
        if not data or not data.get("update_id"):
            return None

        # Handle callback queries (inline keyboard presses)
        callback_query = data.get("callback_query")
        if callback_query:
            await self.answer_callback_query(callback_query["id"])
            cb_msg = callback_query.get("message", {})
            return PlatformMessage(
                id=f"tg_cb_{callback_query.get('id')}",
                platform="telegram",
                sender_id=str(callback_query.get("from", {}).get("id")),
                sender_name=callback_query.get("from", {}).get("first_name", "User"),
                chat_id=str(cb_msg.get("chat", {}).get("id")),
                content=callback_query.get("data", ""),
            )

        msg_data = data.get("message") or data.get("edited_message")
        if not msg_data:
            return None

        sender = msg_data.get("from", {})
        sender_id = str(sender.get("id", ""))
        sender_name = sender.get("first_name", "User")
        chat_id = str(msg_data.get("chat", {}).get("id"))
        msg_id = f"tg_{msg_data.get('message_id')}"

        # Determine content and message type from the update
        content = msg_data.get("text") or msg_data.get("caption") or ""
        message_type = MessageType.TEXT

        if msg_data.get("photo"):
            message_type = MessageType.IMAGE
            # photo is an array of PhotoSize, take the largest (last)
            if not content:
                content = "[Photo]"
        elif msg_data.get("video"):
            message_type = MessageType.VIDEO
            if not content:
                content = "[Video]"
        elif msg_data.get("audio"):
            message_type = MessageType.AUDIO
            if not content:
                content = "[Audio]"
        elif msg_data.get("voice"):
            message_type = MessageType.AUDIO
            if not content:
                content = "[Voice message]"
        elif msg_data.get("document"):
            message_type = MessageType.DOCUMENT
            doc = msg_data["document"]
            if not content:
                content = f"[Document: {doc.get('file_name', 'unknown')}]"
        elif msg_data.get("sticker"):
            message_type = MessageType.STICKER
            sticker = msg_data["sticker"]
            if not content:
                content = f"[Sticker: {sticker.get('emoji', '')}]"
        elif msg_data.get("location"):
            message_type = MessageType.LOCATION
            loc = msg_data["location"]
            content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
        elif msg_data.get("contact"):
            message_type = MessageType.CONTACT
            contact = msg_data["contact"]
            content = f"[Contact: {contact.get('first_name', '')} {contact.get('phone_number', '')}]"

        return PlatformMessage(
            id=msg_id,
            platform="telegram",
            sender_id=sender_id,
            sender_name=sender_name,
            chat_id=chat_id,
            content=content,
            message_type=message_type,
        )

    async def shutdown(self):
        if self.session:
            await self.session.close()
