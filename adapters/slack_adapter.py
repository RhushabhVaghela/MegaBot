"""
Slack Adapter for MegaBot
Provides integration with Slack using slack-sdk
"""

import asyncio
import logging
import os
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

from core.resource_guard import LRUCache

try:
    import slack_sdk
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
except ImportError:
    # Fallback mocks for when slack-sdk is not installed
    from unittest.mock import MagicMock

    slack_sdk = MagicMock()

    class WebClient:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            return MagicMock()

    class SocketModeClient:
        def __init__(self, *args, **kwargs):
            pass

    SocketModeRequest = MagicMock()
    SocketModeResponse = MagicMock()


from adapters.messaging import PlatformMessage, MessageType, PlatformAdapter


@dataclass
class SlackMessage:
    """Slack message object"""

    id: str
    channel_id: str
    user_id: str
    username: str
    text: str
    timestamp: datetime
    thread_ts: Optional[str] = None
    files: List[Dict[str, Any]] = field(default_factory=list)
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    is_dm: bool = False

    @classmethod
    def from_event(cls, event: Dict[str, Any]) -> "SlackMessage":
        return cls(
            id=event.get("ts", ""),
            channel_id=event.get("channel", ""),
            user_id=event.get("user", ""),
            username="",  # Will be filled by API call
            text=event.get("text", ""),
            timestamp=datetime.fromtimestamp(float(event.get("ts", 0))),
            thread_ts=event.get("thread_ts"),
            files=event.get("files", []),
            reactions=[],  # Will be filled by API call
            is_dm=event.get("channel_type") == "im",
        )


class SlackAdapter(PlatformAdapter):
    """
    Slack platform adapter using Slack SDK.

    Features:
    - Text messaging and file sharing
    - Threaded conversations
    - Direct messages and channels
    - Message reactions
    - User mentions and formatting
    - Block Kit support
    """

    def __init__(
        self,
        platform_name: str,
        server: Any,
        bot_token: str,
        app_token: Optional[str] = None,
        signing_secret: Optional[str] = None,
    ):
        """
        Initialize the Slack adapter.

        Args:
            platform_name: Name of the platform ("slack")
            server: Reference to the MegaBotMessagingServer instance
            bot_token: Slack bot token
            app_token: Slack app-level token for socket mode
            signing_secret: Signing secret for webhook verification
        """
        super().__init__(platform_name, server)
        self.bot_token = bot_token
        self.app_token = app_token
        self.signing_secret = signing_secret

        self.client = WebClient(token=bot_token)
        self.socket_client: Optional[SocketModeClient] = None

        self.bot_user_id: Optional[str] = None
        self.is_initialized = False
        self.message_cache: LRUCache[str, Dict[str, Any]] = LRUCache(maxsize=1024)

        self.message_handlers: List[Callable] = []
        self.reaction_handlers: List[Callable] = []
        self.command_handlers: Dict[str, Callable] = {}
        self.event_handlers: Dict[str, Callable] = {}

        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        """Set up default Slack event type registrations.

        Actual socket-mode listeners are attached in _init_socket_mode().
        This pre-registers the event types that the adapter handles so
        callers can inspect ``self.event_handlers`` before the socket is live.
        """
        # Pre-register known event types so the adapter reports which events
        # it can handle even before socket mode connects.
        for event_type in ("message", "reaction_added", "reaction_removed", "app_mention", "member_joined_channel"):
            if event_type not in self.event_handlers:
                self.event_handlers[event_type] = lambda e, _et=event_type: None

    async def initialize(self) -> bool:
        """
        Initialize the Slack adapter.

        Returns:
            True if initialization successful
        """
        try:
            # Test the connection and get bot info
            response = await asyncio.to_thread(self.client.auth_test)

            if response.get("ok"):
                self.bot_user_id = response.get("user_id")
                logger.info("[Slack] Bot authenticated as %s", self.bot_user_id)

                # Initialize socket mode if app token provided
                if self.app_token:
                    await self._init_socket_mode()

                self.is_initialized = True
                return True
            else:
                logger.error("[Slack] Authentication failed: %s", response.get("error"))
                return False

        except Exception as e:
            logger.error("[Slack] Initialization error: %s", e)
            return False

    async def _init_socket_mode(self) -> None:
        """Initialize Socket Mode for real-time events"""
        if not self.app_token:
            return

        self.socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self.client,
        )

        @self.socket_client.socket_mode_request_listener
        async def process_socket_mode_request(client: SocketModeClient, req: SocketModeRequest):
            await self._handle_socket_request(req)

        await asyncio.to_thread(self.socket_client.client.connect)
        logger.info("[Slack] Socket Mode initialized")

    async def _handle_socket_request(self, req: SocketModeRequest) -> None:
        """Handle incoming Socket Mode requests"""
        if req.type == "events_api":
            envelope_id = req.envelope_id
            payload = req.payload

            if payload.get("type") == "event_callback":
                event = payload.get("event", {})
                await self._handle_event(event)

            # Acknowledge the request
            response = SocketModeResponse(envelope_id=envelope_id)
            await asyncio.to_thread(self.socket_client.client.send_socket_mode_response, response)

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        """Handle Slack events"""
        event_type = event.get("type")

        if event_type == "message":
            await self._handle_message_event(event)
        elif event_type == "reaction_added":
            await self._handle_reaction_event(event, "add")
        elif event_type == "reaction_removed":
            await self._handle_reaction_event(event, "remove")
        elif event_type in self.event_handlers:
            handler = self.event_handlers[event_type]
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("[Slack] Event handler error: %s", e)

    async def _handle_message_event(self, event: Dict[str, Any]) -> None:
        """Handle message events"""
        # Skip messages from the bot itself
        if event.get("user") == self.bot_user_id:
            return

        # Skip bot messages
        if event.get("bot_id"):
            return

        platform_msg = await self._to_platform_message(event)

        for handler in self.message_handlers:
            try:
                result = handler(platform_msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("[Slack] Message handler error: %s", e)

    async def _handle_reaction_event(self, event: Dict[str, Any], action: str) -> None:
        """Handle reaction events"""
        for handler in self.reaction_handlers:
            try:
                result = handler(event, action)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("[Slack] Reaction handler error: %s", e)

    async def _to_platform_message(self, event: Dict[str, Any]) -> PlatformMessage:
        """Convert Slack event to PlatformMessage"""
        text = event.get("text", "")
        msg_type = MessageType.TEXT

        if event.get("files"):
            files = event["files"]
            if any(f.get("mimetype", "").startswith("image/") for f in files):
                msg_type = MessageType.IMAGE
            elif any(f.get("mimetype", "").startswith("video/") for f in files):
                msg_type = MessageType.VIDEO
            elif any(f.get("mimetype", "").startswith("audio/") for f in files):
                msg_type = MessageType.AUDIO
            else:
                msg_type = MessageType.DOCUMENT

        # Get user info
        user_id = event.get("user", "")
        username = await self._get_username(user_id)

        return PlatformMessage(
            id=f"slack_{event.get('ts', '')}",
            platform="slack",
            sender_id=user_id,
            sender_name=username,
            chat_id=event.get("channel", ""),
            content=text,
            message_type=msg_type,
            timestamp=datetime.fromtimestamp(float(event.get("ts", 0))),
            reply_to=event.get("thread_ts"),
            metadata={
                "slack_ts": event.get("ts"),
                "slack_channel": event.get("channel"),
                "slack_thread_ts": event.get("thread_ts"),
                "slack_files": event.get("files", []),
                "slack_reactions": [],  # Would need separate API call
                "is_dm": event.get("channel_type") == "im",
            },
        )

    async def _get_username(self, user_id: str) -> str:
        """Get username from user ID"""
        try:
            response = await asyncio.to_thread(self.client.users_info, {"user": user_id})
            if response.get("ok"):
                return response["user"]["name"]
        except Exception as e:
            logger.warning("[Slack] Failed to look up username for %s: %s", user_id, e)
        return f"slack_user_{user_id}"

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> Optional[PlatformMessage]:
        """Send text message to Slack channel."""
        try:
            kwargs = {
                "channel": chat_id,
                "text": text,
            }

            if reply_to:
                kwargs["thread_ts"] = reply_to

            response = await asyncio.to_thread(self.client.chat_postMessage, kwargs)

            if response.get("ok"):
                ts = response.get("ts")
                return PlatformMessage(
                    id=f"slack_{ts}",
                    platform="slack",
                    sender_id=self.bot_user_id or "megabot",
                    sender_name="MegaBot",
                    chat_id=chat_id,
                    content=text,
                    message_type=MessageType.TEXT,
                    timestamp=datetime.now(),
                    reply_to=reply_to,
                    metadata={"slack_ts": ts},
                )

            logger.error("[Slack] Send failed: %s", response.get("error"))
            return None

        except Exception as e:
            logger.error("[Slack] Send text error: %s", e)
            return None

    async def send_media(
        self,
        chat_id: str,
        media_path: str,
        caption: Optional[str] = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> Optional[PlatformMessage]:
        """Send media to Slack channel."""
        try:
            # Upload file first
            with open(media_path, "rb") as f:
                upload_response = await asyncio.to_thread(
                    self.client.files_upload_v2,
                    {
                        "file": f,
                        "filename": os.path.basename(media_path),
                        "title": caption or "Media",
                        "channels": chat_id,
                    },
                )

            if upload_response.get("ok"):
                file_info = upload_response.get("file", {})
                ts = file_info.get("shares", {}).get("public", {}).get(chat_id, [{}])[0].get("ts")

                return PlatformMessage(
                    id=f"slack_{ts or uuid.uuid4().hex[:16]}",
                    platform="slack",
                    sender_id=self.bot_user_id or "megabot",
                    sender_name="MegaBot",
                    chat_id=chat_id,
                    content=caption or "",
                    message_type=media_type,
                    timestamp=datetime.now(),
                    metadata={"slack_file": file_info},
                )

            return None

        except Exception as e:
            logger.error("[Slack] Send media error: %s", e)
            return None

    async def send_document(
        self, chat_id: str, document_path: str, caption: Optional[str] = None
    ) -> Optional[PlatformMessage]:
        """Send document to Slack channel."""
        return await self.send_media(chat_id, document_path, caption, MessageType.DOCUMENT)

    async def download_media(self, message_id: str, save_path: str) -> Optional[str]:
        """Download media from Slack message.

        Uses conversations.history to find the message, extracts the first
        file reference, then downloads it using the files.info URL with the
        bot token for authorisation.  Returns saved file path on success.
        """
        try:
            # Slack files require a Bot token header to download
            # First, retrieve message metadata to find file references
            # message_id in Slack is typically the message ts
            # We need channel context; search recent file shares
            files_resp = await asyncio.to_thread(self.client.files_list, count=20)
            if not files_resp.get("ok"):
                logger.error("[Slack] Could not list files: %s", files_resp.get("error"))
                return None

            for f in files_resp.get("files", []):
                if f.get("id") == message_id or message_id in f.get("shares", {}).get("public", {}).keys():
                    download_url = f.get("url_private_download") or f.get("url_private")
                    if not download_url:
                        continue
                    import urllib.request

                    req = urllib.request.Request(
                        download_url,
                        headers={"Authorization": f"Bearer {self.bot_token}"},
                    )
                    resp = await asyncio.to_thread(urllib.request.urlopen, req)
                    data = resp.read()
                    with open(save_path, "wb") as fp:
                        fp.write(data)
                    return save_path

            logger.warning("[Slack] No downloadable file found for %s", message_id)
            return None
        except Exception as e:
            logger.error("[Slack] Download media error: %s", e)
            return None

    async def make_call(self, chat_id: str, is_video: bool = False) -> bool:
        """Initiate a call (not supported by Slack API)."""
        logger.warning("[Slack] Call initiation not supported for %s", chat_id)
        return False

    async def add_reaction(self, channel_id: str, message_ts: str, emoji: str) -> bool:
        """
        Add a reaction to a message.

        Args:
            channel_id: Channel ID
            message_ts: Message timestamp
            emoji: Emoji name (without colons)

        Returns:
            True on success
        """
        try:
            response = await asyncio.to_thread(
                self.client.reactions_add,
                {"channel": channel_id, "timestamp": message_ts, "name": emoji},
            )
            return response.get("ok", False)

        except Exception as e:
            logger.error("[Slack] Add reaction error: %s", e)
            return False

    async def remove_reaction(self, channel_id: str, message_ts: str, emoji: str) -> bool:
        """
        Remove a reaction from a message.

        Args:
            channel_id: Channel ID
            message_ts: Message timestamp
            emoji: Emoji name

        Returns:
            True on success
        """
        try:
            response = await asyncio.to_thread(
                self.client.reactions_remove,
                {"channel": channel_id, "timestamp": message_ts, "name": emoji},
            )
            return response.get("ok", False)

        except Exception as e:
            logger.error("[Slack] Remove reaction error: %s", e)
            return False

    async def delete_message(self, channel_id: str, message_ts: str) -> bool:
        """
        Delete a message.

        Args:
            channel_id: Channel ID
            message_ts: Message timestamp

        Returns:
            True on success
        """
        try:
            response = await asyncio.to_thread(
                self.client.chat_delete,
                {"channel": channel_id, "ts": message_ts},
            )
            return response.get("ok", False)

        except Exception as e:
            logger.error("[Slack] Delete message error: %s", e)
            return False

    async def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a channel"""
        try:
            response = await asyncio.to_thread(self.client.conversations_info, {"channel": channel_id})

            if response.get("ok"):
                channel = response.get("channel", {})
                return {
                    "id": channel.get("id"),
                    "name": channel.get("name"),
                    "is_private": channel.get("is_private", False),
                    "member_count": channel.get("num_members"),
                    "topic": channel.get("topic", {}).get("value"),
                    "purpose": channel.get("purpose", {}).get("value"),
                    "created": datetime.fromtimestamp(channel.get("created", 0)).isoformat(),
                }

            return None

        except Exception as e:
            logger.error("[Slack] Get channel info error: %s", e)
            return None

    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a user"""
        try:
            response = await asyncio.to_thread(self.client.users_info, {"user": user_id})

            if response.get("ok"):
                user = response.get("user", {})
                return {
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "real_name": user.get("real_name"),
                    "display_name": user.get("profile", {}).get("display_name"),
                    "email": user.get("profile", {}).get("email"),
                    "is_bot": user.get("is_bot", False),
                }

            return None

        except Exception as e:
            logger.error("[Slack] Get user info error: %s", e)
            return None

    def register_message_handler(self, handler: Callable) -> None:
        """Register a message handler"""
        self.message_handlers.append(handler)

    def register_reaction_handler(self, handler: Callable) -> None:
        """Register a reaction handler"""
        self.reaction_handlers.append(handler)

    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a command handler"""
        self.command_handlers[command] = handler

    def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """Register an event handler"""
        self.event_handlers[event_type] = handler

    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.socket_client:
            await asyncio.to_thread(self.socket_client.client.disconnect)
        self.is_initialized = False
        logger.info("[Slack] Adapter shutdown complete")

    def _generate_id(self) -> str:
        """Generate unique message ID"""
        return str(uuid.uuid4())
