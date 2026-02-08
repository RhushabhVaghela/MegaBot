# Core MegaBot functionality
"""
Core business logic and orchestration components for MegaBot.

Imports are lazy to avoid circular dependency with the adapters package.
Use ``from core.orchestrator import MegaBotOrchestrator`` (etc.) directly.
"""

from .config import Config, load_config
from .interfaces import Message
from .llm_providers import LLMProvider, get_llm_provider


def __getattr__(name: str):
    """Lazy-load MegaBotOrchestrator to break the circular import cycle."""
    if name == "MegaBotOrchestrator":
        from .orchestrator import MegaBotOrchestrator

        return MegaBotOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MegaBotOrchestrator",
    "Config",
    "load_config",
    "Message",
    "get_llm_provider",
    "LLMProvider",
]
