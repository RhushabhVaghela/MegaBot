import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import aiofiles
import websockets  # type: ignore
from cryptography.fernet import Fernet  # type: ignore
from cryptography.hazmat.primitives import hashes  # type: ignore
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore

logger = logging.getLogger(__name__)


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACT = "contact"
    STICKER = "sticker"
    CALL = "call"


@dataclass
class MediaAttachment:
    type: MessageType
    filename: str
    mime_type: str
    size: int
    data: bytes = field(repr=False)
    caption: str | None = None
    thumbnail: bytes | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": self.size,
            "data": base64.b64encode(self.data).decode("utf-8"),
            "caption": self.caption,
            "has_thumbnail": self.thumbnail is not None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MediaAttachment":
        return cls(
            type=MessageType(data["type"]),
            filename=data["filename"],
            mime_type=data["mime_type"],
            size=data["size"],
            data=base64.b64decode(data["data"]),
            caption=data.get("caption"),
            thumbnail=base64.b64decode(data["thumbnail"]) if data.get("thumbnail") else None,
        )


@dataclass
class PlatformMessage:
    id: str
    platform: str
    sender_id: str
    sender_name: str
    chat_id: str
    chat_name: str | None = None
    content: str = ""
    message_type: MessageType = MessageType.TEXT
    attachments: list[MediaAttachment] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    is_encrypted: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "content": self.content,
            "message_type": self.message_type.value,
            "attachments": [att.to_dict() for att in self.attachments],
            "timestamp": self.timestamp.isoformat(),
            "reply_to": self.reply_to,
            "metadata": self.metadata,
            "is_encrypted": self.is_encrypted,
        }


class SecureWebSocket:
    password: str  # Always set after __init__ (or ValueError is raised)

    def __init__(self, password: str | None = None):
        resolved = password or os.environ.get("MEGABOT_WS_PASSWORD")
        if not resolved:
            raise ValueError(
                "MEGABOT_WS_PASSWORD must be set via constructor or environment variable. "
                "Refusing to use a hardcoded default."
            )
        self.password = resolved
        self.cipher = self._init_cipher()

    def _init_cipher(self) -> Fernet:
        salt_val = os.environ.get("MEGABOT_ENCRYPTION_SALT")
        if not salt_val:
            raise ValueError("MEGABOT_ENCRYPTION_SALT must be set in environment. Refusing to use a hardcoded default.")
        salt = salt_val.encode()
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        return Fernet(key)

    def encrypt(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt data using Fernet cipher.

        Raises:
            ValueError: If decryption fails (invalid token, corrupted data, etc.)
        """
        try:
            return self.cipher.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            raise ValueError(
                f"Decryption failed: {e}. This may indicate a key mismatch, corrupted data, or a replay attack."
            ) from e


class PlatformAdapter:
    def __init__(self, platform_name: str, server: Any):
        self.platform_name = platform_name
        self.server = server

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> PlatformMessage | None:
        return PlatformMessage(
            id=str(uuid.uuid4()),
            platform=self.platform_name,
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
        return None

    async def send_document(
        self, chat_id: str, document_path: str, caption: str | None = None
    ) -> PlatformMessage | None:
        return None

    async def download_media(self, message_id: str, save_path: str) -> str | None:
        return None

    async def make_call(self, chat_id: str, is_video: bool = False) -> bool:
        logger.info("Initiating %s call to %s", "video" if is_video else "voice", chat_id)
        return True


class MegaBotMessagingServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 18790, enable_encryption: bool = True):
        self.host = host
        self.port = port
        self.enable_encryption = enable_encryption
        self.clients: dict[str, Any] = {}
        self.platform_adapters: dict[str, PlatformAdapter] = {}
        self.message_handlers: list[Callable[[PlatformMessage], Any]] = []
        self.on_connect: Callable[[str, str], Awaitable[None]] | None = None
        self.secure_ws = SecureWebSocket() if enable_encryption else None
        self.media_storage_path = os.environ.get("MEGABOT_MEDIA_PATH", "./media")
        os.makedirs(self.media_storage_path, exist_ok=True)
        self.memu_adapter = None
        self.voice_adapter = None
        self.openclaw = None
        self._shutdown_event = asyncio.Event()

    def register_handler(self, handler: Callable[[PlatformMessage], Any]):
        self.message_handlers.append(handler)

    async def initialize_memu(self, memu_path: str = "./memu", db_url: str = "sqlite:///megabot_memory.db"):
        try:
            from adapters.memu_adapter import MemUAdapter

            self.memu_adapter = MemUAdapter(memu_path, db_url)
            logger.info("memU adapter initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize memU: %s", e)

    async def initialize_voice(self, account_sid: str, auth_token: str, from_number: str):
        try:
            from adapters.voice_adapter import VoiceAdapter

            self.voice_adapter = VoiceAdapter(account_sid, auth_token, from_number)
        except Exception as e:
            logger.error("[Voice] Failed to initialize voice adapter: %s", e)

    async def start(self):
        logger.info("Starting Messaging Server on ws://%s:%s", self.host, self.port)
        async with websockets.serve(self._handle_client, self.host, self.port):
            await self._shutdown_event.wait()
        # Gracefully close remaining client connections
        for client_id, ws in list(self.clients.items()):
            try:
                await ws.close()
            except Exception:
                logger.debug("Failed to close WebSocket for client %s during shutdown", client_id)
        logger.info("Messaging Server shut down.")

    async def shutdown(self):
        """Signal the server to stop accepting connections and shut down."""
        self._shutdown_event.set()

    async def send_message(self, message: PlatformMessage, target_client: str | None = None):
        data = json.dumps(message.to_dict())
        if self.enable_encryption and self.secure_ws:
            data = self.secure_ws.encrypt(data)
        clients_to_send = (
            [target_client] if target_client and target_client in self.clients else list(self.clients.keys())
        )
        for client_id in clients_to_send:
            if client_id not in self.clients:
                continue
            try:
                await self.clients[client_id].send(data)
            except (ConnectionError, RuntimeError, OSError) as e:
                logger.error("Failed to send to %s: %s", client_id, e)
                if client_id in self.clients:
                    del self.clients[client_id]

    async def _handle_client(self, websocket: Any, path: str = ""):
        try:
            client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        except (IndexError, AttributeError, TypeError):
            client_id = f"unknown-{id(websocket)}"
        self.clients[client_id] = websocket
        if self.on_connect:
            await self.on_connect(client_id, "native")
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                await self._process_message(client_id, message)
        except Exception as e:
            # Log unexpected errors; ConnectionClosed is expected on disconnect
            if "ConnectionClosed" not in type(e).__name__:
                logger.error("WebSocket handler error for %s: %s", client_id, e)
        finally:
            if client_id in self.clients:
                del self.clients[client_id]

    async def _process_message(self, client_id: str, raw_message: str):
        try:
            if self.enable_encryption and self.secure_ws:
                raw_message = self.secure_ws.decrypt(raw_message)
            data = json.loads(raw_message)
            msg_type = data.get("type", "message")
            if msg_type == "message":
                await self._handle_platform_message(data)
            elif msg_type == "media_upload":
                await self._handle_media_upload(data)
            elif msg_type == "platform_connect":
                await self._handle_platform_connect(data)
            elif msg_type == "command":
                await self._handle_command(data)
            else:
                logger.warning("Unknown message type: %s", msg_type)
        except Exception as e:
            logger.error("Error processing message from %s: %s", client_id, e)

    async def _handle_platform_message(self, data: dict):
        message = PlatformMessage(
            id=data.get("id", str(uuid.uuid4())),
            platform=data.get("platform", "native"),
            sender_id=data["sender_id"],
            sender_name=data.get("sender_name", "Unknown"),
            chat_id=data["chat_id"],
            content=data.get("content", ""),
            message_type=MessageType(data.get("message_type", "text")),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            metadata=data.get("metadata", {}),
        )
        if "attachments" in data:
            for att_data in data["attachments"]:
                attachment = MediaAttachment.from_dict(att_data)
                message.attachments.append(attachment)
                await self._save_media(attachment)
        for handler in self.message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.warning("Message handler error: %s", e)

    async def _handle_platform_message_from_adapter(self, message: PlatformMessage):
        """Standard handler for messages coming from PlatformAdapters/Signal"""
        for handler in self.message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.warning("Message handler error (from adapter): %s", e)

    async def _handle_media_upload(self, data: dict):
        attachment = MediaAttachment.from_dict(data["attachment"])
        await self._save_media(attachment)

    async def _handle_platform_connect(self, data: dict):
        platform = str(data.get("platform", "unknown"))
        logger.info("Platform connection request: %s", platform)
        if platform == "telegram":
            from .telegram import TelegramAdapter

            token = data.get("credentials", {}).get("token")
            if token:
                adapter = TelegramAdapter(token, self)
                self.platform_adapters[platform] = adapter
                logger.info("Initialized Telegram adapter")
        elif platform == "whatsapp":
            from .whatsapp import WhatsAppAdapter

            adapter = WhatsAppAdapter(platform, self, data.get("config", {}))
            self.platform_adapters[platform] = adapter
            logger.info("Initialized WhatsApp adapter")
        elif platform == "imessage":
            from .imessage import IMessageAdapter

            adapter = IMessageAdapter(platform, self)
            self.platform_adapters[platform] = adapter
            logger.info("Initialized iMessage adapter")
        elif platform == "sms":
            from .sms import SMSAdapter

            adapter = SMSAdapter(platform, self, data.get("config", {}))
            self.platform_adapters[platform] = adapter
            logger.info("Initialized SMS adapter")
        elif platform == "signal":
            from adapters.signal_adapter import SignalAdapter

            creds = data.get("credentials", {})
            config = data.get("config", {})
            phone = str(creds.get("phone_number", ""))
            if phone:
                adapter = SignalAdapter(
                    phone_number=phone,
                    socket_path=config.get("socket_path", "/tmp/signal.socket"),
                    admin_numbers=config.get("admin_numbers", []),
                )

                # Wrap SignalAdapter as a PlatformAdapter
                class SignalPlatformAdapter(PlatformAdapter):
                    def __init__(self, platform_name, server, signal_adapter):
                        super().__init__(platform_name, server)
                        self.signal = signal_adapter

                    async def send_text(self, chat_id, text, reply_to=None):
                        msg_id = await self.signal.send_message(chat_id, text, quote_message_id=reply_to)
                        return PlatformMessage(
                            id=f"signal_{msg_id}" if msg_id else str(uuid.uuid4()),
                            platform=self.platform_name,
                            sender_id="megabot",
                            sender_name="MegaBot",
                            chat_id=chat_id,
                            content=text,
                            reply_to=reply_to,
                        )

                self.platform_adapters[platform] = SignalPlatformAdapter(platform, self, adapter)
                # Hook Signal message handler back to this server
                adapter.register_message_handler(self._handle_platform_message_from_adapter)
                asyncio.create_task(adapter.initialize())
                logger.info("Initialized Signal adapter for %s", phone)
        elif platform == "discord":
            token = data.get("credentials", {}).get("token")
            if token:
                from adapters.discord_adapter import DiscordAdapter

                self.platform_adapters[platform] = DiscordAdapter(platform, self, token)
                logger.info("Initialized Discord adapter")
        elif platform == "slack":
            from adapters.slack_adapter import SlackAdapter

            credentials = data.get("credentials", {})
            if credentials.get("bot_token"):
                self.platform_adapters[platform] = SlackAdapter(
                    platform_name=platform,
                    server=self,
                    bot_token=credentials.get("bot_token"),
                    app_token=credentials.get("app_token"),
                    signing_secret=data.get("config", {}).get("signing_secret"),
                )
                logger.info("Initialized Slack adapter")
        else:
            self.platform_adapters[platform] = PlatformAdapter(platform, self)
            logger.info("Initialized generic adapter for unknown platform: %s", platform)
        if self.on_connect:
            await self.on_connect("", platform)

    async def _handle_command(self, data: dict):
        command = data.get("command")
        args = data.get("args", [])
        logger.info("Command: %s with args: %s", command, args)

    async def _save_media(self, attachment: MediaAttachment) -> str:
        file_hash = hashlib.sha256(attachment.data).hexdigest()[:16]
        # Sanitize filename to prevent path traversal (e.g. "../../etc/cron.d/evil")
        # 1. Strip to basename (removes directory components)
        # 2. Remove any characters that aren't alphanumeric, dot, hyphen, or underscore
        safe_name = os.path.basename(attachment.filename or "unnamed")
        safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
        if not safe_name or safe_name.startswith("."):
            safe_name = "unnamed" + safe_name
        filepath = os.path.join(self.media_storage_path, f"{file_hash}_{safe_name}")
        # Final defense: ensure resolved path is within media_storage_path
        resolved = os.path.realpath(filepath)
        media_root = os.path.realpath(self.media_storage_path)
        if not resolved.startswith(media_root + os.sep) and resolved != media_root:
            raise ValueError(f"Path traversal detected: {attachment.filename!r}")
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(attachment.data)
        return filepath

    def _generate_id(self) -> str:
        return str(uuid.uuid4())
