import logging

import aiofiles
import websockets

from .imessage import IMessageAdapter
from .server import (
    MediaAttachment,
    MegaBotMessagingServer,
    MessageType,
    PlatformAdapter,
    PlatformMessage,
    SecureWebSocket,
)
from .sms import SMSAdapter
from .telegram import TelegramAdapter
from .whatsapp import WhatsAppAdapter

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
