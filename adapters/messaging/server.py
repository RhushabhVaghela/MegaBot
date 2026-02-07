import asyncio
import websockets  # type: ignore
import json
import os
import base64
import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from cryptography.fernet import Fernet  # type: ignore
from cryptography.hazmat.primitives import hashes  # type: ignore
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore
import aiofiles


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
    caption: Optional[str] = None
    thumbnail: Optional[bytes] = field(default=None, repr=False)

    def to_dict(self) -> Dict:
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
    def from_dict(cls, data: Dict) -> "MediaAttachment":
        return cls(
            type=MessageType(data["type"]),
            filename=data["filename"],
            mime_type=data["mime_type"],
            size=data["size"],
            data=base64.b64decode(data["data"]),
            caption=data.get("caption"),
            thumbnail=base64.b64decode(data["thumbnail"])
            if data.get("thumbnail")
            else None,
        )


@dataclass
class PlatformMessage:
    id: str
    platform: str
    sender_id: str
    sender_name: str
    chat_id: str
    chat_name: Optional[str] = None
    content: str = ""
    message_type: MessageType = MessageType.TEXT
    attachments: List[MediaAttachment] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    reply_to: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_encrypted: bool = False

    def to_dict(self) -> Dict:
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
    def __init__(self, password: Optional[str] = None):
        self.password = password or os.environ.get("MEGABOT_WS_PASSWORD")
        if not self.password:
            raise ValueError(
                "MEGABOT_WS_PASSWORD must be set via constructor or environment variable. "
                "Refusing to use a hardcoded default."
            )
        self.cipher = self._init_cipher()

    def _init_cipher(self) -> Fernet:
        salt_val = os.environ.get("MEGABOT_ENCRYPTION_SALT")
        if not salt_val:
            raise ValueError(
                "MEGABOT_ENCRYPTION_SALT must be set in environment. "
                "Refusing to use a hardcoded default."
            )
        salt = salt_val.encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        return Fernet(key)

    def encrypt(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        try:
            return self.cipher.decrypt(encrypted_data.encode()).decode()
        except Exception:
            return encrypted_data


class PlatformAdapter:
    def __init__(self, platform_name: str, server: Any):
        self.platform_name = platform_name
        self.server = server

    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> Optional[PlatformMessage]:
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
        caption: Optional[str] = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> Optional[PlatformMessage]:
        return None

    async def send_document(
        self, chat_id: str, document_path: str, caption: Optional[str] = None
    ) -> Optional[PlatformMessage]:
        return None

    async def download_media(self, message_id: str, save_path: str) -> Optional[str]:
        return None

    async def make_call(self, chat_id: str, is_video: bool = False) -> bool:
        print(
            f"[{self.platform_name}] Initiating {'video' if is_video else 'voice'} call to {chat_id}"
        )
        return True


class MegaBotMessagingServer:
    def __init__(
        self, host: str = "127.0.0.1", port: int = 18790, enable_encryption: bool = True
    ):
        self.host = host
        self.port = port
        self.enable_encryption = enable_encryption
        self.clients: Dict[str, Any] = {}
        self.platform_adapters: Dict[str, PlatformAdapter] = {}
        self.message_handlers: List[Callable[[PlatformMessage], Any]] = []
        self.on_connect: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.secure_ws = SecureWebSocket() if enable_encryption else None
        self.media_storage_path = os.environ.get("MEGABOT_MEDIA_PATH", "./media")
        os.makedirs(self.media_storage_path, exist_ok=True)
        self.memu_adapter = None
        self.voice_adapter = None
        self.openclaw = None

    def register_handler(self, handler: Callable[[PlatformMessage], Any]):
        self.message_handlers.append(handler)

    async def initialize_memu(
        self, memu_path: str = "./memu", db_url: str = "sqlite:///megabot_memory.db"
    ):
        try:
            from adapters.memu_adapter import MemUAdapter

            self.memu_adapter = MemUAdapter(memu_path, db_url)
            print("memU adapter initialized successfully")
        except Exception as e:
            print(f"Failed to initialize memU: {e}")

    async def initialize_voice(
        self, account_sid: str, auth_token: str, from_number: str
    ):
        try:
            from adapters.voice_adapter import VoiceAdapter

            self.voice_adapter = VoiceAdapter(account_sid, auth_token, from_number)
        except Exception:
            pass

    async def start(self):
        print(f"Starting Messaging Server on ws://{self.host}:{self.port}")
        async with websockets.serve(self._handle_client, self.host, self.port):
            await asyncio.Future()

    async def send_message(
        self, message: PlatformMessage, target_client: Optional[str] = None
    ):
        data = json.dumps(message.to_dict())
        if self.enable_encryption and self.secure_ws:
            data = self.secure_ws.encrypt(data)
        clients_to_send = (
            [target_client]
            if target_client and target_client in self.clients
            else list(self.clients.keys())
        )
        for client_id in clients_to_send:
            if client_id not in self.clients:
                continue
            try:
                await self.clients[client_id].send(data)
            except Exception as e:
                print(f"Failed to send to {client_id}: {e}")
                if client_id in self.clients:
                    del self.clients[client_id]

    async def _handle_client(self, websocket: Any, path: str = ""):
        try:
            client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        except Exception:
            client_id = f"unknown-{id(websocket)}"
        self.clients[client_id] = websocket
        if self.on_connect:
            await self.on_connect(client_id, "native")
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                await self._process_message(client_id, message)
        except Exception:
            pass
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
                print(f"Unknown message type: {msg_type}")
        except Exception as e:
            print(f"Error processing message from {client_id}: {e}")

    async def _handle_platform_message(self, data: Dict):
        message = PlatformMessage(
            id=data.get("id", str(uuid.uuid4())),
            platform=data.get("platform", "native"),
            sender_id=data["sender_id"],
            sender_name=data.get("sender_name", "Unknown"),
            chat_id=data["chat_id"],
            content=data.get("content", ""),
            message_type=MessageType(data.get("message_type", "text")),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if data.get("timestamp")
            else datetime.now(),
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
            except Exception:
                pass

    async def _handle_platform_message_from_adapter(self, message: PlatformMessage):
        """Standard handler for messages coming from PlatformAdapters/Signal"""
        for handler in self.message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception:
                pass

    async def _handle_media_upload(self, data: Dict):
        attachment = MediaAttachment.from_dict(data["attachment"])
        await self._save_media(attachment)

    async def _handle_platform_connect(self, data: Dict):
        platform = str(data.get("platform", "unknown"))
        print(f"Platform connection request: {platform}")
        if platform == "telegram":
            from .telegram import TelegramAdapter

            token = data.get("credentials", {}).get("token")
            if token:
                adapter = TelegramAdapter(token, self)
                self.platform_adapters[platform] = adapter
                print("Initialized Telegram adapter")
        elif platform == "whatsapp":
            from .whatsapp import WhatsAppAdapter

            adapter = WhatsAppAdapter(platform, self, data.get("config", {}))
            self.platform_adapters[platform] = adapter
            print("Initialized WhatsApp adapter")
        elif platform == "imessage":
            from .imessage import IMessageAdapter

            adapter = IMessageAdapter(platform, self)
            self.platform_adapters[platform] = adapter
            print("Initialized iMessage adapter")
        elif platform == "sms":
            from .sms import SMSAdapter

            adapter = SMSAdapter(platform, self, data.get("config", {}))
            self.platform_adapters[platform] = adapter
            print("Initialized SMS adapter")
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
                        msg_id = await self.signal.send_message(
                            chat_id, text, quote_message_id=reply_to
                        )
                        return PlatformMessage(
                            id=f"signal_{msg_id}" if msg_id else str(uuid.uuid4()),
                            platform=self.platform_name,
                            sender_id="megabot",
                            sender_name="MegaBot",
                            chat_id=chat_id,
                            content=text,
                            reply_to=reply_to,
                        )

                self.platform_adapters[platform] = SignalPlatformAdapter(
                    platform, self, adapter
                )
                # Hook Signal message handler back to this server
                adapter.register_message_handler(
                    self._handle_platform_message_from_adapter
                )
                asyncio.create_task(adapter.initialize())
                print(f"Initialized Signal adapter for {phone}")
        elif platform == "discord":
            token = data.get("credentials", {}).get("token")
            if token:
                from adapters.discord_adapter import DiscordAdapter

                self.platform_adapters[platform] = DiscordAdapter(platform, self, token)
                print("Initialized Discord adapter")
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
                print("Initialized Slack adapter")
        else:
            self.platform_adapters[platform] = PlatformAdapter(platform, self)
            print(f"Initialized generic adapter for unknown platform: {platform}")
        if self.on_connect:
            await self.on_connect("", platform)

    async def _handle_command(self, data: Dict):
        command = data.get("command")
        args = data.get("args", [])
        print(f"Command: {command} with args: {args}")

    async def _save_media(self, attachment: MediaAttachment) -> str:
        file_hash = hashlib.sha256(attachment.data).hexdigest()[:16]
        filepath = os.path.join(
            self.media_storage_path, f"{file_hash}_{attachment.filename}"
        )
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(attachment.data)
        return filepath

    def _generate_id(self) -> str:
        return str(uuid.uuid4())
