"""MegaBot — Production-ready, local-first AI orchestrator.

Unifies OpenClaw, memU, and MCP into a single secure agentic brain
with multi-channel messaging (Telegram, WhatsApp, Discord, Slack,
Signal, iMessage, SMS), 17+ LLM providers, and a WebSocket dashboard.

Quick start::

    from megabot import Config, load_config, Message
    config = load_config()

    # Or use the orchestrator directly:
    from megabot import MegaBotOrchestrator
"""

__version__ = "1.2.0"
__author__ = "Rhushabh Vaghela"

from megabot.core.config import Config, load_config
from megabot.core.interfaces import Message
from megabot.core.llm_providers import LLMProvider, get_llm_provider


def __getattr__(name: str):
    """Lazy-load heavy objects to avoid circular imports at package level."""
    if name == "MegaBotOrchestrator":
        from megabot.core.orchestrator import MegaBotOrchestrator

        return MegaBotOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "MegaBotOrchestrator",
    "Config",
    "load_config",
    "Message",
    "get_llm_provider",
    "LLMProvider",
]
