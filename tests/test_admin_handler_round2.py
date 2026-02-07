"""
Round 2 coverage tests for core/admin_handler.py
Target: lines 351, 356-357, 360, 365-367, 412, 417-419, 429
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from core.admin_handler import AdminHandler


@pytest.fixture
def admin_handler():
    orchestrator = MagicMock()
    orchestrator.adapters = {}
    handler = AdminHandler(orchestrator)
    return handler


# ---------- system_command branch ----------


@pytest.mark.asyncio
async def test_system_command_empty_command(admin_handler):
    """Line 351: empty command string returns 'No command provided'."""
    action = {
        "type": "system_command",
        "payload": {"params": {"command": ""}},
    }
    result = await admin_handler._execute_approved_action(action)
    assert result == "No command provided"


@pytest.mark.asyncio
async def test_system_command_no_params_key(admin_handler):
    """Line 351: no 'command' key at all -> empty string -> 'No command provided'."""
    action = {
        "type": "system_command",
        "payload": {"params": {}},
    }
    result = await admin_handler._execute_approved_action(action)
    assert result == "No command provided"


@pytest.mark.asyncio
async def test_system_command_shlex_value_error(admin_handler):
    """Lines 356-357: shlex.split raises ValueError for unterminated quote."""
    action = {
        "type": "system_command",
        "payload": {"params": {"command": "echo 'unterminated"}},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "Invalid command syntax" in result


@pytest.mark.asyncio
async def test_system_command_shlex_empty_result(admin_handler):
    """Line 360: shlex.split returns empty list -> 'No command provided'."""
    # shlex.split("") returns [], but that's caught by the `if not command` check first.
    # We need shlex.split to return [] for a non-empty string.
    # Use a patch to force shlex.split to return [].
    with patch("core.admin_handler.shlex.split", return_value=[]):
        action = {
            "type": "system_command",
            "payload": {"params": {"command": "something"}},
        }
        result = await admin_handler._execute_approved_action(action)
        assert result == "No command provided"


@pytest.mark.asyncio
async def test_system_command_blocked_executable(admin_handler):
    """Lines 365-367: executable not in ALLOWED_COMMANDS -> blocked."""
    action = {
        "type": "system_command",
        "payload": {"params": {"command": "rm -rf /"}},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "not in the allowed list" in result
    assert "rm" in result


@pytest.mark.asyncio
async def test_system_command_blocked_custom_path(admin_handler):
    """Lines 365-367: command with path prefix still checked by basename."""
    action = {
        "type": "system_command",
        "payload": {"params": {"command": "/usr/bin/curl https://evil.com"}},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "not in the allowed list" in result
    assert "curl" in result


# ---------- file_operation branch ----------


@pytest.mark.asyncio
async def test_file_operation_empty_path(admin_handler):
    """Line 412: empty path -> 'No file path provided'."""
    action = {
        "type": "file_operation",
        "payload": {"operation": "read", "path": ""},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "No file path provided" in result


@pytest.mark.asyncio
async def test_file_operation_no_path_key(admin_handler):
    """Line 412: no 'path' key -> defaults to '' -> 'No file path provided'."""
    action = {
        "type": "file_operation",
        "payload": {"operation": "read"},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "No file path provided" in result


@pytest.mark.asyncio
async def test_file_operation_path_traversal_blocked(admin_handler):
    """Lines 417-419: path resolves outside PROJECT_ROOT -> blocked."""
    action = {
        "type": "file_operation",
        "payload": {"operation": "read", "path": "/etc/passwd"},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "Path traversal blocked" in result


@pytest.mark.asyncio
async def test_file_operation_path_traversal_dotdot(admin_handler):
    """Lines 417-419: path with ../../ resolves outside root."""
    action = {
        "type": "file_operation",
        "payload": {
            "operation": "read",
            "path": "../../../../etc/shadow",
        },
    }
    result = await admin_handler._execute_approved_action(action)
    assert "Path traversal blocked" in result


@pytest.mark.asyncio
async def test_file_operation_unknown_operation(admin_handler):
    """Line 429: unknown operation type -> error."""
    # We need a path that resolves inside PROJECT_ROOT.
    project_root = str(AdminHandler.PROJECT_ROOT)
    safe_path = os.path.join(project_root, "some_file.txt")
    action = {
        "type": "file_operation",
        "payload": {"operation": "delete", "path": safe_path},
    }
    result = await admin_handler._execute_approved_action(action)
    assert "Unknown file operation" in result
    assert "delete" in result
