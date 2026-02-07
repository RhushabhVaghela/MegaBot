import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch
from core.memory.mcp_server import MemoryServer


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
def mock_chat_memory():
    """Mock ChatMemoryManager."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_user_identity():
    """Mock UserIdentityManager."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_knowledge_memory():
    """Mock KnowledgeMemoryManager."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_backup_manager():
    """Mock MemoryBackupManager."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def memory_server(
    temp_db,
    mock_chat_memory,
    mock_user_identity,
    mock_knowledge_memory,
    mock_backup_manager,
):
    """Create MemoryServer with mocked managers."""
    server = MemoryServer(temp_db)
    server.chat_memory = mock_chat_memory
    server.user_identity = mock_user_identity
    server.knowledge_memory = mock_knowledge_memory
    server.backup_manager = mock_backup_manager
    return server


@pytest.mark.asyncio
async def test_init_default_path():
    """Test MemoryServer initialization with default path."""
    server = MemoryServer()
    expected_path = os.path.join(os.getcwd(), "megabot_memory.db")
    assert server.db_path == expected_path
    # Should have all managers initialized
    assert hasattr(server, "chat_memory")
    assert hasattr(server, "user_identity")
    assert hasattr(server, "knowledge_memory")
    assert hasattr(server, "backup_manager")


@pytest.mark.asyncio
async def test_init_custom_path(temp_db):
    """Test MemoryServer initialization with custom path."""
    server = MemoryServer(temp_db)
    assert server.db_path == temp_db


@pytest.mark.asyncio
async def test_chat_write(memory_server, mock_chat_memory):
    """Test chat_write delegates to chat_memory."""
    mock_chat_memory.write.return_value = True

    result = await memory_server.chat_write("chat1", "discord", "user", "hello")

    mock_chat_memory.write.assert_called_once_with("chat1", "discord", "user", "hello", None)
    assert result is True


@pytest.mark.asyncio
async def test_chat_write_with_metadata(memory_server, mock_chat_memory):
    """Test chat_write with metadata."""
    mock_chat_memory.write.return_value = True
    metadata = {"user_id": "123"}

    result = await memory_server.chat_write("chat1", "discord", "user", "hello", metadata)

    mock_chat_memory.write.assert_called_once_with("chat1", "discord", "user", "hello", metadata)
    assert result is True


@pytest.mark.asyncio
async def test_chat_read(memory_server, mock_chat_memory):
    """Test chat_read delegates to chat_memory."""
    expected_history = [{"role": "user", "content": "hello"}]
    mock_chat_memory.read.return_value = expected_history

    result = await memory_server.chat_read("chat1", 10)

    mock_chat_memory.read.assert_called_once_with("chat1", 10)
    assert result == expected_history


@pytest.mark.asyncio
async def test_chat_forget(memory_server, mock_chat_memory):
    """Test chat_forget delegates to chat_memory."""
    mock_chat_memory.forget.return_value = True

    result = await memory_server.chat_forget("chat1", 100)

    mock_chat_memory.forget.assert_called_once_with("chat1", 100)
    assert result is True


@pytest.mark.asyncio
async def test_get_all_chat_ids(memory_server, mock_chat_memory):
    """Test get_all_chat_ids delegates to chat_memory."""
    expected_ids = ["chat1", "chat2"]
    mock_chat_memory.get_all_chat_ids.return_value = expected_ids

    result = await memory_server.get_all_chat_ids()

    mock_chat_memory.get_all_chat_ids.assert_called_once()
    assert result == expected_ids


@pytest.mark.asyncio
async def test_link_identity(memory_server, mock_user_identity):
    """Test link_identity delegates to user_identity."""
    mock_user_identity.link_identity.return_value = True

    result = await memory_server.link_identity("internal_123", "discord", "user_456")

    mock_user_identity.link_identity.assert_called_once_with("internal_123", "discord", "user_456")
    assert result is True


@pytest.mark.asyncio
async def test_get_unified_id(memory_server, mock_user_identity):
    """Test get_unified_id delegates to user_identity."""
    mock_user_identity.get_unified_id.return_value = "internal_123"

    result = await memory_server.get_unified_id("discord", "user_456")

    mock_user_identity.get_unified_id.assert_called_once_with("discord", "user_456")
    assert result == "internal_123"


@pytest.mark.asyncio
async def test_memory_write(memory_server, mock_knowledge_memory):
    """Test memory_write delegates to knowledge_memory."""
    mock_knowledge_memory.write.return_value = "Memory written successfully"

    result = await memory_server.memory_write("key1", "decision", "content", ["tag1"])

    mock_knowledge_memory.write.assert_called_once_with("key1", "decision", "content", ["tag1"])
    assert result == "Memory written successfully"


@pytest.mark.asyncio
async def test_memory_read(memory_server, mock_knowledge_memory):
    """Test memory_read delegates to knowledge_memory."""
    expected_memory = {"key": "key1", "content": "test"}
    mock_knowledge_memory.read.return_value = expected_memory

    result = await memory_server.memory_read("key1")

    mock_knowledge_memory.read.assert_called_once_with("key1")
    assert result == expected_memory


@pytest.mark.asyncio
async def test_memory_search(memory_server, mock_knowledge_memory):
    """Test memory_search delegates to knowledge_memory."""
    expected_results = [{"key": "key1", "content": "test"}]
    mock_knowledge_memory.search.return_value = expected_results

    result = await memory_server.memory_search(query="test", limit=10)

    mock_knowledge_memory.search.assert_called_once_with("test", None, None, 10, "updated_at DESC")
    assert result == expected_results


@pytest.mark.asyncio
async def test_backup_database(memory_server, mock_backup_manager):
    """Test backup_database delegates to backup_manager."""
    mock_backup_manager.create_backup.return_value = "/path/to/backup.zip"

    result = await memory_server.backup_database("encryption_key")

    mock_backup_manager.create_backup.assert_called_once_with("encryption_key")
    assert result == "/path/to/backup.zip"


@pytest.mark.asyncio
async def test_memory_stats(
    memory_server,
    mock_chat_memory,
    mock_user_identity,
    mock_knowledge_memory,
    mock_backup_manager,
):
    """Test memory_stats aggregates from all managers."""
    mock_chat_memory.get_aggregate_stats.return_value = {"message_count": 10}
    mock_user_identity.get_identity_stats.return_value = {"linked_users": 5}
    mock_knowledge_memory.get_stats.return_value = {"total_memories": 20}
    mock_backup_manager.get_backup_stats.return_value = {"backups_created": 3}

    result = await memory_server.memory_stats()

    expected = {
        "chat": {"message_count": 10},
        "identities": {"linked_users": 5},
        "knowledge": {"total_memories": 20},
        "backups": {"backups_created": 3},
        "db_path": memory_server.db_path,
    }
    assert result == expected


@pytest.mark.asyncio
async def test_memory_stats_error_handling(memory_server, mock_chat_memory):
    """Test memory_stats error handling."""
    mock_chat_memory.get_aggregate_stats.side_effect = Exception("DB Error")

    result = await memory_server.memory_stats()

    assert result == {"error": "DB Error"}


@pytest.mark.asyncio
async def test_handle_tool_call_chat_write(memory_server, mock_chat_memory):
    """Test handle_tool_call for chat_write."""
    mock_chat_memory.write.return_value = True

    result = await memory_server.handle_tool_call(
        "chat_write",
        {"chat_id": "chat1", "platform": "discord", "role": "user", "content": "hello"},
    )

    assert result is True


@pytest.mark.asyncio
async def test_handle_tool_call_chat_read(memory_server, mock_chat_memory):
    """Test handle_tool_call for chat_read."""
    expected_history = [{"role": "user", "content": "hello"}]
    mock_chat_memory.read.return_value = expected_history

    result = await memory_server.handle_tool_call("chat_read", {"chat_id": "chat1", "limit": 10})

    assert result == expected_history


@pytest.mark.asyncio
async def test_handle_tool_call_chat_forget(memory_server, mock_chat_memory):
    """Test handle_tool_call for chat_forget."""
    mock_chat_memory.forget.return_value = True

    result = await memory_server.handle_tool_call("chat_forget", {"chat_id": "chat1", "max_history": 100})

    assert result is True


@pytest.mark.asyncio
async def test_handle_tool_call_memory_write(memory_server, mock_knowledge_memory):
    """Test handle_tool_call for memory_write."""
    mock_knowledge_memory.write.return_value = "Written"

    result = await memory_server.handle_tool_call(
        "memory_write",
        {"key": "key1", "type": "decision", "content": "content", "tags": ["tag1"]},
    )

    assert result == "Written"


@pytest.mark.asyncio
async def test_handle_tool_call_memory_read(memory_server, mock_knowledge_memory):
    """Test handle_tool_call for memory_read."""
    expected_memory = {"key": "key1"}
    mock_knowledge_memory.read.return_value = expected_memory

    result = await memory_server.handle_tool_call("memory_read", {"key": "key1"})

    assert result == expected_memory


@pytest.mark.asyncio
async def test_handle_tool_call_memory_search(memory_server, mock_knowledge_memory):
    """Test handle_tool_call for memory_search."""
    expected_results = [{"key": "key1"}]
    mock_knowledge_memory.search.return_value = expected_results

    result = await memory_server.handle_tool_call("memory_search", {"query": "test", "limit": 5})

    assert result == expected_results


@pytest.mark.asyncio
async def test_handle_tool_call_link_identity(memory_server, mock_user_identity):
    """Test handle_tool_call for link_identity."""
    mock_user_identity.link_identity.return_value = True

    result = await memory_server.handle_tool_call(
        "link_identity",
        {
            "internal_id": "internal_123",
            "platform": "discord",
            "platform_id": "user_456",
        },
    )

    assert result is True


@pytest.mark.asyncio
async def test_handle_tool_call_get_unified_id(memory_server, mock_user_identity):
    """Test handle_tool_call for get_unified_id."""
    mock_user_identity.get_unified_id.return_value = "internal_123"

    result = await memory_server.handle_tool_call("get_unified_id", {"platform": "discord", "platform_id": "user_456"})

    assert result == "internal_123"


@pytest.mark.asyncio
async def test_handle_tool_call_backup_database(memory_server, mock_backup_manager):
    """Test handle_tool_call for backup_database."""
    mock_backup_manager.create_backup.return_value = "/path/to/backup.zip"

    result = await memory_server.handle_tool_call("backup_database", {"encryption_key": "key"})

    assert result == "/path/to/backup.zip"


@pytest.mark.asyncio
async def test_handle_tool_call_memory_stats(
    memory_server,
    mock_chat_memory,
    mock_user_identity,
    mock_knowledge_memory,
    mock_backup_manager,
):
    """Test handle_tool_call for memory_stats."""
    mock_chat_memory.get_aggregate_stats.return_value = {"count": 1}
    mock_user_identity.get_identity_stats.return_value = {"count": 2}
    mock_knowledge_memory.get_stats.return_value = {"count": 3}
    mock_backup_manager.get_backup_stats.return_value = {"count": 4}

    result = await memory_server.handle_tool_call("memory_stats", {})

    assert "chat" in result
    assert "identities" in result
    assert "knowledge" in result
    assert "backups" in result


@pytest.mark.asyncio
async def test_handle_tool_call_unknown_tool(memory_server):
    """Test handle_tool_call with unknown tool name."""
    with pytest.raises(ValueError, match="Unknown memory tool: unknown_tool"):
        await memory_server.handle_tool_call("unknown_tool", {})


@pytest.mark.asyncio
async def test_init_legacy_db_exception():
    """Test MemoryServer init when _run_migrations fails due to DB error."""
    with (
        patch("core.memory.mcp_server.ChatMemoryManager"),
        patch("core.memory.mcp_server.UserIdentityManager"),
        patch("core.memory.mcp_server.KnowledgeMemoryManager"),
        patch("core.memory.mcp_server.MemoryBackupManager"),
        patch("sqlite3.connect", side_effect=Exception("DB Error")),
    ):
        # _run_migrations re-raises, so construction should fail
        with pytest.raises(Exception, match="DB Error"):
            MemoryServer("/tmp/failed_db.db")
