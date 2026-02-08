# Platform adapters for MegaBot
"""
Adapters for integrating MegaBot with various messaging platforms and external services.
"""

from .messaging import MegaBotMessagingServer, MessageType, PlatformMessage
from .unified_gateway import ClientConnection, ConnectionType, UnifiedGateway

__all__ = [
    "UnifiedGateway",
    "ConnectionType",
    "ClientConnection",
    "MegaBotMessagingServer",
    "PlatformMessage",
    "MessageType",
]
