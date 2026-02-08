from unittest.mock import MagicMock, patch

import pytest

from adapters.nanobot_adapter import NanobotAdapter
from core.interfaces import Message


@pytest.mark.asyncio
async def test_nanobot_adapter_initialization():
    """Test NanobotAdapter initialization with mock fallback."""
    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    # Should use mock fallback since nanobot isn't installed
    assert adapter.market_analyzer is not None
    assert adapter.routine_engine is not None
    assert adapter.messenger is not None


@pytest.mark.asyncio
async def test_nanobot_adapter_initialization_with_installed_package():
    """Test initialization when nanobot is available as installed package."""
    mock_market_analyzer = MagicMock()
    mock_routine_engine = MagicMock()
    mock_messenger = MagicMock()

    mock_nanobot_core = MagicMock()
    mock_nanobot_core.MarketAnalyzer = MagicMock(return_value=mock_market_analyzer)
    mock_nanobot_core.RoutineEngine = MagicMock(return_value=mock_routine_engine)
    mock_nanobot_core.Messenger = MagicMock(return_value=mock_messenger)

    with patch.dict("sys.modules", {"nanobot.core": mock_nanobot_core}):
        adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

        # Should use real classes when import succeeds
        assert adapter.market_analyzer is mock_market_analyzer
        assert adapter.routine_engine is mock_routine_engine
        assert adapter.messenger is mock_messenger


@pytest.mark.asyncio
async def test_nanobot_adapter_initialization_with_path_finding():
    """Test initialization when nanobot is found via path searching."""
    mock_market_analyzer = MagicMock()
    mock_routine_engine = MagicMock()
    mock_messenger = MagicMock()

    mock_nanobot_core = MagicMock()
    mock_nanobot_core.MarketAnalyzer = MagicMock(return_value=mock_market_analyzer)
    mock_nanobot_core.RoutineEngine = MagicMock(return_value=mock_routine_engine)
    mock_nanobot_core.Messenger = MagicMock(return_value=mock_messenger)

    import_attempts = [0]  # Use list to modify from inner function

    def mock_import_side_effect(name, *args, **kwargs):
        if name == "nanobot.core" and import_attempts[0] < 1:
            import_attempts[0] += 1
            raise ImportError("No module named 'nanobot'")
        elif name == "nanobot.core":
            return mock_nanobot_core
        return MagicMock()

    with (
        patch("sys.path") as mock_sys_path,
        patch("os.path.exists", side_effect=lambda p: p == "/valid/path/src"),
        patch("builtins.__import__", side_effect=mock_import_side_effect),
    ):
        adapter = NanobotAdapter("/valid/path", "telegram_token", "whatsapp_token")

        # Should find path and use real classes
        assert adapter.market_analyzer is mock_market_analyzer
        assert adapter.routine_engine is mock_routine_engine
        assert adapter.messenger is mock_messenger
        assert adapter.nanobot_path == "/valid/path/src"


@pytest.mark.asyncio
async def test_nanobot_adapter_initialization_failure_fallback():
    """Test initialization when MarketAnalyzer constructor fails."""
    mock_nanobot_core = MagicMock()
    mock_nanobot_core.MarketAnalyzer = MagicMock(side_effect=Exception("Init failed"))
    mock_nanobot_core.RoutineEngine = MagicMock()
    mock_nanobot_core.Messenger = MagicMock()

    with patch.dict("sys.modules", {"nanobot.core": mock_nanobot_core}):
        adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

        # Should use dummy fallback
        assert hasattr(adapter.market_analyzer, "analyze_market")
        assert hasattr(adapter.routine_engine, "run_routine")
        assert hasattr(adapter.messenger, "send_telegram")
        assert hasattr(adapter.messenger, "send_whatsapp")

        # Test that dummy methods return error dicts
        result = await adapter.analyze_market("TEST")
        assert result == {"error": "Service unavailable"}

        result = await adapter.run_routine("test_routine", {})
        assert result == {"error": "Service unavailable"}

        success = await adapter.messenger.send_telegram("123", "test")
        assert success is False

        success = await adapter.messenger.send_whatsapp("123", "test")
        assert success is False


@pytest.mark.asyncio
async def test_send_message_unsupported_platform(caplog):
    """Test sending message with unsupported platform."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    message = Message(
        content="Hello",
        sender="test_user",
        metadata={"recipient": "unknown", "platform": "unknown"},
    )

    # Should not raise exception, just log warning
    with caplog.at_level(logging.WARNING, logger="adapters.nanobot_adapter"):
        await adapter.send_message(message)

    assert any("Unsupported platform unknown or recipient unknown" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_message_whatsapp(caplog):
    """Test sending message via WhatsApp."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    message = Message(
        content="Hello WhatsApp",
        sender="test_user",
        metadata={"recipient": "+1234567890", "platform": "whatsapp"},
    )

    # Should not raise exception
    with caplog.at_level(logging.DEBUG, logger="adapters.nanobot_adapter"):
        await adapter.send_message(message)

    assert any("Mock WhatsApp: Sent 'Hello WhatsApp' to +1234567890" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_message_whatsapp_by_recipient_prefix(caplog):
    """Test sending message via WhatsApp based on recipient prefix."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    message = Message(
        content="Hello WhatsApp",
        sender="test_user",
        metadata={"recipient": "+1234567890", "platform": "unknown"},
    )

    # Should detect whatsapp from + prefix even with unknown platform
    with caplog.at_level(logging.DEBUG, logger="adapters.nanobot_adapter"):
        await adapter.send_message(message)

    assert any("Mock WhatsApp: Sent 'Hello WhatsApp' to +1234567890" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_receive_message():
    """Test receiving message returns placeholder when no webhook configured."""
    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    result = await adapter.receive_message()
    assert result.sender == "system"
    assert "not configured" in result.content.lower() or "not configured" in str(result.metadata)


@pytest.mark.asyncio
async def test_analyze_market():
    """Test market analysis functionality."""
    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    result = await adapter.analyze_market("AAPL")

    assert isinstance(result, dict)
    assert "symbol" in result or "error" in result


@pytest.mark.asyncio
async def test_run_routine():
    """Test running routines."""
    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    result = await adapter.run_routine("daily_report", {"symbol": "GOOGL"})

    assert isinstance(result, dict)
    assert "status" in result or "error" in result


@pytest.mark.asyncio
async def test_messenger_methods(caplog):
    """Test messenger methods directly."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    with caplog.at_level(logging.DEBUG, logger="adapters.nanobot_adapter"):
        # Test telegram send
        await adapter.messenger.send_telegram("123", "test telegram")
        assert any("Mock Telegram: Sent 'test telegram' to 123" in r.message for r in caplog.records)

        caplog.clear()

        # Test whatsapp send
        await adapter.messenger.send_whatsapp("456", "test whatsapp")
        assert any("Mock WhatsApp: Sent 'test whatsapp' to 456" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_message_telegram(caplog):
    """Test sending message via Telegram."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    message = Message(
        content="Hello Telegram",
        sender="test_user",
        metadata={"recipient": "123456789", "platform": "telegram"},
    )

    with caplog.at_level(logging.DEBUG, logger="adapters.nanobot_adapter"):
        await adapter.send_message(message)

    assert any("Mock Telegram: Sent 'Hello Telegram' to 123456789" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_message_telegram_by_recipient_prefix(caplog):
    """Test sending message via Telegram based on recipient prefix."""
    import logging

    adapter = NanobotAdapter("/fake/path", "telegram_token", "whatsapp_token")

    message = Message(
        content="Hello Telegram",
        sender="test_user",
        metadata={"recipient": "@testuser", "platform": "unknown"},
    )

    with caplog.at_level(logging.DEBUG, logger="adapters.nanobot_adapter"):
        await adapter.send_message(message)

    assert any("Mock Telegram: Sent 'Hello Telegram' to @testuser" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_nanobot_adapter_path_finding_import_error():
    """Test path finding when import fails after finding path."""
    import_attempts = [0]

    def mock_import_side_effect(name, *args, **kwargs):
        if name == "nanobot.core":
            # Always fail for nanobot.core
            raise ImportError("Import failed")
        return MagicMock()

    with (
        patch("sys.path") as mock_sys_path,
        patch("os.path.exists", side_effect=lambda p: p == "/valid/path/src"),
        patch("builtins.__import__", side_effect=mock_import_side_effect),
        patch("builtins.print") as mock_print,
    ):
        adapter = NanobotAdapter("/valid/path", "t", "w")

        # Should fall back to mock because import failed
        assert "MockMarketAnalyzer" in str(type(adapter.market_analyzer))
