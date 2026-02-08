"""Tests for SMS adapter"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock twilio before any other imports
mock_twilio = MagicMock()
sys.modules["twilio"] = mock_twilio
sys.modules["twilio.rest"] = mock_twilio
sys.modules["twilio.request_validator"] = mock_twilio

from adapters.messaging.sms import SMSAdapter


@pytest.fixture
def sms_adapter():
    server = MagicMock()
    config = {
        "twilio_account_sid": "test_sid",
        "twilio_auth_token": "test_token",
        "twilio_from_number": "+1234567890",
    }
    return SMSAdapter("sms", server, config)


@pytest.mark.asyncio
async def test_sms_initialization_success(sms_adapter):
    """Test successful SMS adapter initialization"""
    with patch("twilio.rest.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        result = await sms_adapter.initialize()
        assert result is True
        assert sms_adapter.client is not None


@pytest.mark.asyncio
async def test_sms_initialization_missing_credentials():
    """Test initialization fails with missing credentials"""
    server = MagicMock()
    adapter = SMSAdapter("sms", server, {})  # Empty config
    result = await adapter.initialize()
    assert result is False


@pytest.mark.asyncio
async def test_sms_initialization_import_error(sms_adapter):
    """Test initialization when twilio import fails"""
    with patch.dict("sys.modules", {"twilio.rest": None}):
        result = await sms_adapter.initialize()
        assert result is False


@pytest.mark.asyncio
async def test_sms_send_text_success(sms_adapter):
    """Test sending SMS text message successfully"""
    mock_message = MagicMock()
    mock_message.sid = "SM123456789"

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_message)
    sms_adapter.client = mock_client
    sms_adapter.from_number = "+1234567890"

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_executor = MagicMock()
        mock_executor.run_in_executor = AsyncMock(return_value=mock_message)
        mock_loop.return_value = mock_executor

        result = await sms_adapter.send_text("+1987654321", "Test message")

        assert result is not None
        assert result.platform == "sms"
        assert result.content == "Test message"
        assert result.chat_id == "+1987654321"


@pytest.mark.asyncio
async def test_sms_send_text_no_client():
    """Test sending SMS without initialized client returns None"""
    server = MagicMock()
    adapter = SMSAdapter("sms", server, {})

    result = await adapter.send_text("+1987654321", "Test message")

    # Without client/from_number, send_text should return None
    assert result is None


@pytest.mark.asyncio
async def test_sms_send_text_failure(sms_adapter):
    """Test SMS send failure handling"""
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(side_effect=Exception("Twilio error"))
    sms_adapter.client = mock_client
    sms_adapter.from_number = "+1234567890"

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_executor = MagicMock()
        mock_executor.run_in_executor = MagicMock(side_effect=Exception("Twilio error"))
        mock_loop.return_value = mock_executor

        result = await sms_adapter.send_text("+1987654321", "Test message")
        assert result is None


@pytest.mark.asyncio
async def test_sms_shutdown():
    """Test SMS adapter shutdown"""
    server = MagicMock()
    adapter = SMSAdapter("sms", server, {})
    # Should not raise any errors
    await adapter.shutdown()
