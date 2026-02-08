"""Secure file-operation tools executed on behalf of sub-agents.

Extracted from :pymod:`core.agent_coordinator` to keep that module under
500 lines. All functions accept an ``orchestrator`` reference (typed via
``TYPE_CHECKING``) and the agent/tool context needed to enforce workspace
confinement, symlink rejection, TOCTOU mitigation, and size limits.

Also hosts the shared ``_audit`` helper used by both this module and
:pymod:`core.agent_coordinator`.

See Also
--------
core.agent_coordinator : orchestrates sub-agent lifecycle and delegates
    ``read_file`` / ``write_file`` tool calls to this module.
"""

import errno
import json as _json
import logging
import os
import stat as _stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.orchestrator import MegaBotOrchestrator

logger = logging.getLogger("megabot.agent_coordinator")
logger_audit = logging.getLogger("megabot.audit")


# ---------------------------------------------------------------------------
# Shared audit helper
# ---------------------------------------------------------------------------


def _audit(event: str, **data):
    """Emit a structured JSON audit event to the ``megabot.audit`` logger.

    Best-effort and intentionally small: tests and production can attach
    handlers to ``megabot.audit`` to route structured events to a file or
    remote sink.
    """
    try:
        payload = {"event": event, "timestamp": datetime.utcnow().isoformat() + "Z"}
        payload.update(data)
        logger_audit.info(_json.dumps(payload))
    except Exception:
        # Never raise from an audit path
        logger.debug("Failed to emit audit event: %s", event)


# ---------------------------------------------------------------------------
# Path validation helpers
# ---------------------------------------------------------------------------


def validate_path(orchestrator: "MegaBotOrchestrator", p: str) -> tuple[bool, str]:
    """Validate *p* is inside the configured workspace and not a symlink.

    Returns ``(True, resolved_path_str)`` on success or
    ``(False, reason_str)`` on denial.
    """
    try:
        if not p:
            return False, "Empty path"
        workspace = Path(orchestrator.config.paths.get("workspaces", os.getcwd())).resolve()
        candidate = Path(p)

        # Interpret relative paths as relative to the workspace.
        if not candidate.is_absolute():
            candidate = workspace.joinpath(candidate)

        try:
            cand_resolved = candidate.resolve()
        except OSError:
            return False, "Path resolution error"

        # Deny symlinks explicitly (fast path).
        if candidate.is_symlink():
            return False, "Symlink paths are not allowed"

        try:
            cand_resolved.relative_to(workspace)
        except ValueError:
            return False, "Path outside workspace"

        return True, str(cand_resolved)
    except Exception as e:
        return False, f"Path validation error: {e}"


def safe_lstat(path_str: str):
    """Return ``os.lstat(path_str)`` or *None* on any error."""
    try:
        return os.lstat(path_str)
    except FileNotFoundError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# read_file tool
# ---------------------------------------------------------------------------


async def read_file(
    orchestrator: "MegaBotOrchestrator",
    agent_name: str,
    tool_input: dict,
    read_limit: int,
) -> str:
    """Execute the ``read_file`` tool with workspace confinement and TOCTOU mitigation."""
    path = str(tool_input.get("path", ""))

    ok, info = validate_path(orchestrator, path)
    if not ok:
        logger.warning(
            "read_file denied: agent=%s path=%s reason=%s",
            agent_name,
            path,
            info,
        )
        _audit("read_file.denied", agent=agent_name, path=path, reason=info)
        return f"Security Error: read_file denied: {info}"

    resolved = info
    pre_stat = safe_lstat(resolved)

    flags = os.O_RDONLY
    use_no_follow = hasattr(os, "O_NOFOLLOW")
    if use_no_follow:
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(resolved, flags)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EPERM, errno.EACCES):
            logger.warning(
                "read_file os.open denied: agent=%s path=%s errno=%s err=%s",
                agent_name,
                resolved,
                e.errno,
                e,
            )
            _audit(
                "read_file.os_open_denied",
                agent=agent_name,
                path=resolved,
                errno=e.errno,
                err=str(e),
            )
            return f"Security Error: read_file denied: possible symlink or permission error ({e})"
        # Fallback to safe builtin open as last resort
        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                data = f.read()
                if len(data.encode("utf-8")) > read_limit:
                    return f"Security Error: read_file denied: file too large ({len(data.encode('utf-8'))} bytes)"
                return data
        except Exception as e2:
            return f"Security Error: read_file denied: {e2}"

    try:
        post_stat = os.fstat(fd)
        # If file existed before and its identity changed -> abort
        if pre_stat is not None and (pre_stat.st_ino != post_stat.st_ino or pre_stat.st_dev != post_stat.st_dev):
            os.close(fd)
            logger.warning(
                "read_file TOCTOU detected: agent=%s path=%s",
                agent_name,
                resolved,
            )
            _audit("read_file.toctou_detected", agent=agent_name, path=resolved)
            return "Security Error: read_file denied: TOCTOU detected"

        # Enforce size limit
        try:
            size = post_stat.st_size
            if size > read_limit:
                os.close(fd)
                logger.warning(
                    "read_file denied (too large): agent=%s path=%s size=%s",
                    agent_name,
                    resolved,
                    size,
                )
                _audit(
                    "read_file.too_large",
                    agent=agent_name,
                    path=resolved,
                    size=size,
                )
                return f"Security Error: read_file denied: file too large ({size} bytes)"
        except (AttributeError, TypeError) as e:
            logger.warning(
                "Failed to enforce size limit on read_file: agent=%s path=%s err=%s", agent_name, resolved, e
            )

        # Read file content in chunks
        chunks = []
        remaining = post_stat.st_size if hasattr(post_stat, "st_size") else None
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            if remaining is not None:
                remaining -= len(chunk)
                if remaining <= 0:
                    break
        data = b"".join(chunks).decode("utf-8", errors="replace")
        os.close(fd)
        return data
    except Exception as e:
        try:
            os.close(fd)
        except Exception as e2:
            logger.debug("Failed to close fd during read_file error cleanup: %s", e2)
        logger.warning(
            "read_file denied (exception): agent=%s path=%s err=%s",
            agent_name,
            resolved,
            e,
        )
        _audit(
            "read_file.exception",
            agent=agent_name,
            path=resolved,
            err=str(e),
        )
        return f"Security Error: read_file denied: {e}"


# ---------------------------------------------------------------------------
# write_file tool
# ---------------------------------------------------------------------------


async def write_file(
    orchestrator: "MegaBotOrchestrator",
    agent_name: str,
    tool_input: dict,
) -> str:
    """Execute the ``write_file`` tool with atomic writes and TOCTOU mitigation."""
    path = str(tool_input.get("path", ""))
    content = str(tool_input.get("content", ""))

    ok, info = validate_path(orchestrator, path)
    if not ok:
        logger.warning(
            "write_file denied: agent=%s path=%s reason=%s",
            agent_name,
            path,
            info,
        )
        _audit("write_file.denied", agent=agent_name, path=path, reason=info)
        return f"Security Error: write_file denied: {info}"

    resolved = Path(info)
    parent_dir = resolved.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    pre_stat = safe_lstat(str(resolved))

    fd, tmp_path = tempfile.mkstemp(dir=str(parent_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            tf.write(content)

        # Re-check lstat on destination before replacing.
        post_stat = safe_lstat(str(resolved))
        if post_stat is not None:
            # If destination is a symlink -> deny
            try:
                if _stat.S_ISLNK(post_stat.st_mode):
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        logger.debug("Failed to unlink tmp_path during symlink deny cleanup: %s", e)
                    logger.warning(
                        "write_file denied (dest symlink): agent=%s path=%s",
                        agent_name,
                        resolved,
                    )
                    _audit(
                        "write_file.dest_symlink",
                        agent=agent_name,
                        path=str(resolved),
                    )
                    return "Security Error: write_file denied: destination is a symlink"
            except Exception as e:
                logger.warning(
                    "Failed to check symlink status on write_file dest: agent=%s path=%s err=%s",
                    agent_name,
                    resolved,
                    e,
                )

            # If pre-existed and identity changed -> abort
            if pre_stat is not None and (pre_stat.st_ino != post_stat.st_ino or pre_stat.st_dev != post_stat.st_dev):
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.debug("Failed to unlink tmp_path during TOCTOU deny cleanup: %s", e)
                logger.warning(
                    "write_file TOCTOU detected: agent=%s path=%s",
                    agent_name,
                    resolved,
                )
                _audit(
                    "write_file.toctou_detected",
                    agent=agent_name,
                    path=str(resolved),
                )
                return "Security Error: write_file denied: TOCTOU detected"

        # Atomically replace the destination with our temp file.
        os.replace(tmp_path, str(resolved))

        # Post-replace verification: check the destination is not a symlink.
        final_stat = safe_lstat(str(resolved))
        if final_stat is not None:
            try:
                if _stat.S_ISLNK(final_stat.st_mode):
                    try:
                        os.unlink(str(resolved))
                    except Exception as e:
                        logger.debug("Failed to unlink symlink during post-replace cleanup: %s", e)
                    logger.warning(
                        "write_file TOCTOU post-replace symlink: agent=%s path=%s",
                        agent_name,
                        resolved,
                    )
                    _audit(
                        "write_file.toctou_post_replace",
                        agent=agent_name,
                        path=str(resolved),
                    )
                    return "Security Error: write_file denied: TOCTOU detected (post-replace)"
            except Exception as e:
                logger.warning(
                    "Failed to check post-replace symlink on write_file: agent=%s path=%s err=%s",
                    agent_name,
                    resolved,
                    e,
                )
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception as e2:
            logger.debug("Failed to unlink tmp_path during write_file error cleanup: %s", e2)
        logger.error(
            "write_file failed: agent=%s path=%s err=%s",
            agent_name,
            resolved,
            e,
        )
        _audit(
            "write_file.exception",
            agent=agent_name,
            path=str(resolved),
            err=str(e),
        )
        return f"Tool execution error: {e}"

    return f"File '{resolved}' written successfully."
