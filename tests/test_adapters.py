#!/usr/bin/env python3
"""Test script for enhanced IMessageAdapter and SMSAdapter."""

import asyncio
import os
from adapters.messaging import (
    IMessageAdapter,
    SMSAdapter,
    MegaBotMessagingServer,
)


import pytest


@pytest.mark.asyncio
async def test_imessage_adapter():
    """Test IMessageAdapter with mock config."""
    print("Testing IMessageAdapter...")
    adapter = IMessageAdapter("imessage", None)

    # Test without BlueBubbles server (should fallback)
    result = await adapter.send_text("test_chat", "Hello from iMessage!")
    # On non-macOS, returns None as expected
    assert result is None

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_sms_adapter():
    """Test SMSAdapter with mock config."""
    # Mock Twilio credentials
    os.environ["TWILIO_ACCOUNT_SID"] = "mock_sid"
    os.environ["TWILIO_AUTH_TOKEN"] = "mock_token"
    os.environ["TWILIO_FROM_NUMBER"] = "+1234567890"

    adapter = SMSAdapter("sms", None)

    # Test send_text (should fallback to print)
    result = await adapter.send_text("+0987654321", "Hello from SMS!")
    assert result is not None
    assert result.platform == "sms"


@pytest.mark.asyncio
async def test_server_initialization():
    """Test server initializes without errors."""
    server = MegaBotMessagingServer()
    assert server.host == "127.0.0.1"
    assert server.port == 18790


async def main():
    """Run all tests."""
    print("Running adapter tests...\n")

    await test_imessage_adapter()
    print()

    await test_sms_adapter()
    print()

    await test_server_initialization()
    print()

    print("All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
