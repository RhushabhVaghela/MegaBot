import logging

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

logger = logging.getLogger(__name__)


async def main():
    """Main entrypoint for the messaging server."""
    server = MegaBotMessagingServer()

    async def log_msg(msg):
        logger.info("New Message: %s", msg.content)

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
