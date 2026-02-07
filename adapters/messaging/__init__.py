from .server import (
    MegaBotMessagingServer,
    PlatformMessage,
    MessageType,
    MediaAttachment,
    PlatformAdapter,
    SecureWebSocket,
)
from .whatsapp import WhatsAppAdapter
from .telegram import TelegramAdapter
from .imessage import IMessageAdapter
from .sms import SMSAdapter
import websockets
import aiofiles


async def main():
    """Main entrypoint for the messaging server."""
    server = MegaBotMessagingServer(
        host="127.0.0.1", port=18790, enable_encryption=True
    )

    async def log_msg(msg):
        print(f"New Message: {msg.content}")

    server.register_handler(log_msg)
    await server.start()


__all__ = [
    "MegaBotMessagingServer",
    "PlatformMessage",
    "MessageType",
    "MediaAttachment",
    "PlatformAdapter",
    "SecureWebSocket",
    "WhatsAppAdapter",
    "TelegramAdapter",
    "IMessageAdapter",
    "SMSAdapter",
    "main",
    "websockets",
    "aiofiles",
]
