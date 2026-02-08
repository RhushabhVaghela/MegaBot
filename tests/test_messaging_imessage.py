"""Tests for iMessage adapter"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from megabot.adapters.messaging.imessage import IMessageAdapter


@pytest.fixture
def imessage_adapter():
    server = MagicMock()
    return IMessageAdapter("imessage", server)


@pytest.mark.asyncio
async def test_imessage_send_text_macos_success(imessage_adapter):
    """Test successful iMessage sending on macOS"""
    imessage_adapter.is_macos = True

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await imessage_adapter.send_text("+1234567890", "Test message")

        assert result is not None
        assert result.platform == "imessage"
        assert result.content == "Test message"
        assert mock_exec.called


@pytest.mark.asyncio
async def test_imessage_send_text_macos_failure(imessage_adapter):
    """Test iMessage sending failure on macOS (osascript error)"""
    imessage_adapter.is_macos = True

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"Error message")
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await imessage_adapter.send_text("+1234567890", "Test message")
        assert result is None


@pytest.mark.asyncio
async def test_imessage_send_text_not_macos(imessage_adapter):
    """Test iMessage sending on non-macOS platforms"""
    imessage_adapter.is_macos = False

    result = await imessage_adapter.send_text("+1234567890", "Test message")
    assert result is None


@pytest.mark.asyncio
async def test_imessage_send_text_exception(imessage_adapter):
    """Test iMessage sending with subprocess exception"""
    imessage_adapter.is_macos = True

    with patch("asyncio.create_subprocess_exec", side_effect=OSError("Subprocess error")):
        result = await imessage_adapter.send_text("+1234567890", "Test message")
        assert result is None


@pytest.mark.asyncio
async def test_imessage_shutdown(imessage_adapter):
    """Test iMessage adapter shutdown"""
    await imessage_adapter.shutdown()
