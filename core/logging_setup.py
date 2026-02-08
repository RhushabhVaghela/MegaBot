import logging
import os
from logging.handlers import RotatingFileHandler


def attach_audit_file_handler(
    path: str = "logs/audit.log", maxBytes: int = 5 * 1024 * 1024, backupCount: int = 5
) -> RotatingFileHandler:
    """Attach a rotating file handler for the `megabot.audit` logger.

    This is an opt-in helper. Call it early in your process (before agents run)
    to persist structured audit events emitted by `megabot.audit` to disk.

    The audit logger expects JSON-formatted messages from callers (the
    AgentCoordinator's `_audit` helper emits compact JSON strings). The
    handler below writes the raw log message to the file so they are valid
    JSON Lines (one JSON object per line).
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    handler = RotatingFileHandler(path, maxBytes=maxBytes, backupCount=backupCount, encoding="utf-8")
    # The AgentCoordinator already emits JSON strings; keep the handler
    # formatter minimal so we preserve JSON lines intact.
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)

    audit_logger = logging.getLogger("megabot.audit")
    # Avoid adding duplicate handlers if called multiple times
    existing = [type(h) for h in audit_logger.handlers]
    if RotatingFileHandler not in existing:
        audit_logger.addHandler(handler)
    # Also ensure the logger is not swallowing INFO messages
    audit_logger.setLevel(logging.INFO)

    return handler
