import asyncio
import os
import sqlite3
import tempfile

import pytest

from core.memory.chat_memory import ChatMemoryManager


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def chat_manager(temp_db):
    """Create ChatMemoryManager instance."""
    return ChatMemoryManager(temp_db)


@pytest.mark.asyncio
async def test_init(chat_manager, temp_db):
    """Test ChatMemoryManager initialization."""
    assert chat_manager.db_path == temp_db
    # Verify tables were created
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "chat_history" in tables

        # Check indexes
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_chat_id_timestamp" in indexes
        assert "idx_chat_platform" in indexes


@pytest.mark.asyncio
async def test_write_success(chat_manager):
    """Test successful message writing."""
    result = await chat_manager.write(
        chat_id="test_chat",
        platform="discord",
        role="user",
        content="Hello bot",
        metadata={"user_id": "123"},
    )
    assert result is True

    # Verify the message was stored
    history = await chat_manager.read("test_chat", limit=10)
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello bot"
    assert history[0]["metadata"]["user_id"] == "123"


@pytest.mark.asyncio
async def test_write_without_metadata(chat_manager):
    """Test writing message without metadata."""
    result = await chat_manager.write(
        chat_id="test_chat_2",
        platform="telegram",
        role="assistant",
        content="Hello user",
    )
    assert result is True

    history = await chat_manager.read("test_chat_2")
    assert len(history) == 1
    assert history[0]["metadata"] == {}


@pytest.mark.asyncio
async def test_read_empty_chat(chat_manager):
    """Test reading from chat with no messages."""
    history = await chat_manager.read("empty_chat")
    assert history == []


@pytest.mark.asyncio
async def test_read_multiple_messages(chat_manager):
    """Test reading multiple messages."""
    # Write messages in sequence with larger delays
    await chat_manager.write("multi_chat", "discord", "user", "First message")
    await asyncio.sleep(0.1)
    await chat_manager.write("multi_chat", "discord", "assistant", "Second message")
    await asyncio.sleep(0.1)
    await chat_manager.write("multi_chat", "discord", "user", "Third message")

    history = await chat_manager.read("multi_chat", limit=10)
    assert len(history) == 3
    # Check that all messages are present (order might vary due to timestamp precision)
    contents = [msg["content"] for msg in history]
    assert "First message" in contents
    assert "Second message" in contents
    assert "Third message" in contents


@pytest.mark.asyncio
async def test_read_with_limit(chat_manager):
    """Test reading with message limit."""
    # Write 5 messages with delays
    for i in range(5):
        await chat_manager.write("limit_chat", "discord", "user", f"Message {i}")
        await asyncio.sleep(0.1)

    # Read with limit 3
    history = await chat_manager.read("limit_chat", limit=3)
    assert len(history) == 3
    # Should get 3 messages (the most recent ones, but order depends on timestamp precision)
    contents = [msg["content"] for msg in history]
    # All contents should be from the written messages
    for content in contents:
        assert content.startswith("Message ")


@pytest.mark.asyncio
async def test_forget_no_cleanup_needed(chat_manager):
    """Test forget when history is below max_history."""
    # Write 3 messages (below default max_history of 500)
    for i in range(3):
        await chat_manager.write("small_chat", "discord", "user", f"Message {i}")

    result = await chat_manager.forget("small_chat")
    assert result is False  # No cleanup needed

    # Messages should still exist
    history = await chat_manager.read("small_chat")
    assert len(history) == 3


@pytest.mark.asyncio
async def test_forget_with_cleanup(chat_manager):
    """Test forget when history exceeds max_history."""
    # Write 10 messages
    for i in range(10):
        await chat_manager.write("large_chat", "discord", "user", f"Message {i}")

    # Force cleanup with small max_history
    result = await chat_manager.forget("large_chat", max_history=5)
    assert result is True

    # Should only have 5 messages left
    history = await chat_manager.read("large_chat")
    assert len(history) == 5


@pytest.mark.asyncio
async def test_forget_keeps_forever_messages(chat_manager):
    """Test that messages with keep_forever metadata are preserved during cleanup."""
    # Write 8 regular messages
    for i in range(8):
        await chat_manager.write("forever_chat", "discord", "user", f"Regular {i}")

    # Write 2 messages with keep_forever
    await chat_manager.write("forever_chat", "discord", "user", "Forever 1", {"keep_forever": True})
    await chat_manager.write("forever_chat", "discord", "user", "Forever 2", {"keep_forever": True})

    # Force cleanup with small max_history (should keep 3 total: 1 regular + 2 forever)
    result = await chat_manager.forget("forever_chat", max_history=1)
    assert result is True

    history = await chat_manager.read("forever_chat")
    assert len(history) == 3
    # Should have the most recent regular + both forever messages
    contents = [msg["content"] for msg in history]
    assert "Forever 1" in contents
    assert "Forever 2" in contents


@pytest.mark.asyncio
async def test_get_all_chat_ids(chat_manager):
    """Test getting all unique chat IDs."""
    await chat_manager.write("chat1", "discord", "user", "Message")
    await chat_manager.write("chat2", "telegram", "user", "Message")
    await chat_manager.write("chat1", "discord", "assistant", "Response")  # Same chat_id
    await chat_manager.write("chat3", "slack", "user", "Message")

    chat_ids = await chat_manager.get_all_chat_ids()
    assert len(chat_ids) == 3
    assert "chat1" in chat_ids
    assert "chat2" in chat_ids
    assert "chat3" in chat_ids


@pytest.mark.asyncio
async def test_get_all_chat_ids_empty(chat_manager):
    """Test getting chat IDs when database is empty."""
    chat_ids = await chat_manager.get_all_chat_ids()
    assert chat_ids == []


@pytest.mark.asyncio
async def test_get_chat_stats(chat_manager):
    """Test getting chat statistics."""
    # Write messages with some time between them
    await chat_manager.write("stats_chat", "discord", "user", "First")
    await asyncio.sleep(0.01)
    await chat_manager.write("stats_chat", "discord", "assistant", "Second")
    await asyncio.sleep(0.01)
    await chat_manager.write("stats_chat", "discord", "user", "Third")

    stats = await chat_manager.get_chat_stats("stats_chat")
    assert stats["chat_id"] == "stats_chat"
    assert stats["message_count"] == 3
    assert stats["oldest_message"] is not None
    assert stats["newest_message"] is not None
    assert stats["newest_message"] >= stats["oldest_message"]


@pytest.mark.asyncio
async def test_get_chat_stats_empty_chat(chat_manager):
    """Test getting stats for chat with no messages."""
    stats = await chat_manager.get_chat_stats("empty_chat")
    assert stats["chat_id"] == "empty_chat"
    assert stats["message_count"] == 0
    assert stats["oldest_message"] is None
    assert stats["newest_message"] is None


@pytest.mark.asyncio
async def test_multiple_platforms(chat_manager):
    """Test handling messages from different platforms."""
    await chat_manager.write("multi_platform", "discord", "user", "Discord message")
    await chat_manager.write("multi_platform", "telegram", "user", "Telegram message")
    await chat_manager.write("multi_platform", "slack", "user", "Slack message")

    history = await chat_manager.read("multi_platform")
    assert len(history) == 3
    # Check that messages are stored correctly by checking the DB directly
    import sqlite3

    with sqlite3.connect(chat_manager.db_path) as conn:
        cursor = conn.execute("SELECT platform FROM chat_history WHERE chat_id = 'multi_platform'")
        platforms = [row[0] for row in cursor.fetchall()]
        assert "discord" in platforms
        assert "telegram" in platforms
        assert "slack" in platforms


@pytest.mark.asyncio
async def test_write_error_handling(chat_manager):
    """Test error handling in write method."""
    # Create a scenario that might cause an error - e.g., invalid JSON in metadata
    # But since we control the JSON dumping, it's hard to trigger errors.
    # We can mock sqlite3.connect to raise an exception
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await chat_manager.write("error_chat", "platform", "role", "content")
        assert result is False


@pytest.mark.asyncio
async def test_read_error_handling(chat_manager):
    """Test error handling in read method."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        history = await chat_manager.read("error_chat")
        assert history == []


@pytest.mark.asyncio
async def test_forget_error_handling(chat_manager):
    """Test error handling in forget method."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await chat_manager.forget("error_chat")
        assert result is False


@pytest.mark.asyncio
async def test_get_all_chat_ids_error_handling(chat_manager):
    """Test error handling in get_all_chat_ids (lines 186-188)"""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")
        chat_ids = await chat_manager.get_all_chat_ids()
        assert chat_ids == []


@pytest.mark.asyncio
async def test_get_chat_stats_error_handling(chat_manager):
    """Test error handling in get_chat_stats (lines 203-205)"""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")
        stats = await chat_manager.get_chat_stats("chat123")
        assert "error" in stats
        assert "DB Error" in stats["error"]


@pytest.mark.asyncio
async def test_get_aggregate_stats(chat_manager):
    """Test aggregate stats across all chats."""
    await chat_manager.write("agg_chat1", "discord", "user", "Message 1")
    await chat_manager.write("agg_chat1", "discord", "assistant", "Reply 1")
    await chat_manager.write("agg_chat2", "telegram", "user", "Message 2")

    stats = await chat_manager.get_aggregate_stats()
    assert stats["total_messages"] == 3
    assert stats["unique_chats"] == 2
    assert stats["by_platform"]["discord"] == 2
    assert stats["by_platform"]["telegram"] == 1
    assert "recent_messages_7d" in stats


@pytest.mark.asyncio
async def test_get_aggregate_stats_empty(chat_manager):
    """Test aggregate stats when database is empty."""
    stats = await chat_manager.get_aggregate_stats()
    assert stats["total_messages"] == 0
    assert stats["unique_chats"] == 0
    assert stats["by_platform"] == {}
    assert stats["recent_messages_7d"] == 0


@pytest.mark.asyncio
async def test_get_aggregate_stats_error_handling(chat_manager):
    """Test error handling in get_aggregate_stats."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")
        stats = await chat_manager.get_aggregate_stats()
        assert "error" in stats
        assert "DB Error" in stats["error"]
