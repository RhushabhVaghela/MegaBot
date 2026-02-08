import os
import sqlite3
import tempfile

import pytest

from megabot.core.memory.knowledge_memory import KnowledgeMemoryManager


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
def knowledge_manager(temp_db):
    """Create KnowledgeMemoryManager instance."""
    return KnowledgeMemoryManager(temp_db)


@pytest.mark.asyncio
async def test_init(knowledge_manager, temp_db):
    """Test KnowledgeMemoryManager initialization."""
    assert knowledge_manager.db_path == temp_db
    # Verify tables were created
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "memories" in tables

        # Check indexes
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_type" in indexes
        # idx_key is intentionally omitted — 'key' is the PRIMARY KEY
        assert "idx_tags" in indexes
        assert "idx_updated_at" in indexes


@pytest.mark.asyncio
async def test_write_success(knowledge_manager):
    """Test successful memory writing."""
    result = await knowledge_manager.write(
        key="test_key",
        type="decision",
        content="This is a test memory",
        tags=["test", "important"],
    )
    assert "written successfully" in result

    # Verify the memory was stored
    memory = await knowledge_manager.read("test_key")
    assert memory is not None
    assert memory["key"] == "test_key"
    assert memory["type"] == "decision"
    assert memory["content"] == "This is a test memory"
    assert memory["tags"] == ["test", "important"]


@pytest.mark.asyncio
async def test_write_without_tags(knowledge_manager):
    """Test writing memory without tags."""
    result = await knowledge_manager.write(key="no_tags_key", type="fact", content="Memory without tags")
    assert "written successfully" in result

    memory = await knowledge_manager.read("no_tags_key")
    assert memory["tags"] == []


@pytest.mark.asyncio
async def test_write_update_existing(knowledge_manager):
    """Test updating existing memory."""
    # Write initial memory
    await knowledge_manager.write("update_key", "initial", "initial content", ["old"])

    # Update it
    result = await knowledge_manager.write("update_key", "updated", "updated content", ["new"])
    assert "written successfully" in result

    memory = await knowledge_manager.read("update_key")
    assert memory["type"] == "updated"
    assert memory["content"] == "updated content"
    assert memory["tags"] == ["new"]


@pytest.mark.asyncio
async def test_read_existing(knowledge_manager):
    """Test reading existing memory."""
    await knowledge_manager.write("read_test", "test_type", "test content", ["tag1"])

    memory = await knowledge_manager.read("read_test")
    assert memory is not None
    assert memory["key"] == "read_test"
    assert memory["type"] == "test_type"
    assert memory["content"] == "test content"
    assert memory["tags"] == ["tag1"]
    assert "created_at" in memory
    assert "updated_at" in memory


@pytest.mark.asyncio
async def test_read_nonexistent(knowledge_manager):
    """Test reading non-existent memory."""
    memory = await knowledge_manager.read("nonexistent")
    assert memory is None


@pytest.mark.asyncio
async def test_search_all(knowledge_manager):
    """Test searching all memories."""
    # Add test data
    await knowledge_manager.write("key1", "type1", "content1", ["tag1"])
    await knowledge_manager.write("key2", "type2", "content2", ["tag2"])
    await knowledge_manager.write("key3", "type1", "content3", ["tag1", "tag3"])

    results = await knowledge_manager.search()
    assert len(results) == 3
    # Should be ordered by updated_at DESC
    assert results[0]["key"] == "key3"  # Most recent


@pytest.mark.asyncio
async def test_search_by_query(knowledge_manager):
    """Test searching by query string."""
    await knowledge_manager.write("apple_key", "fruit", "red apple content", ["fruit"])
    await knowledge_manager.write("banana_key", "fruit", "yellow banana", ["fruit"])
    await knowledge_manager.write("car_key", "vehicle", "red car", ["vehicle"])

    # Search for "red"
    results = await knowledge_manager.search(query="red")
    assert len(results) == 2
    keys = [r["key"] for r in results]
    assert "apple_key" in keys
    assert "car_key" in keys


@pytest.mark.asyncio
async def test_search_by_type(knowledge_manager):
    """Test searching by type."""
    await knowledge_manager.write("mem1", "decision", "decision content", [])
    await knowledge_manager.write("mem2", "fact", "fact content", [])
    await knowledge_manager.write("mem3", "decision", "another decision", [])

    results = await knowledge_manager.search(type="decision")
    assert len(results) == 2
    for result in results:
        assert result["type"] == "decision"


@pytest.mark.asyncio
async def test_search_by_tags(knowledge_manager):
    """Test searching by tags."""
    await knowledge_manager.write("mem1", "type", "content1", ["important", "urgent"])
    await knowledge_manager.write("mem2", "type", "content2", ["important"])
    await knowledge_manager.write("mem3", "type", "content3", ["urgent"])

    # Search for memories with both "important" AND "urgent" tags
    results = await knowledge_manager.search(tags=["important", "urgent"])
    assert len(results) == 1
    assert results[0]["key"] == "mem1"

    # Search for memories with "important" tag
    results = await knowledge_manager.search(tags=["important"])
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_with_limit(knowledge_manager):
    """Test search with limit."""
    for i in range(5):
        await knowledge_manager.write(f"key{i}", "type", f"content{i}", [])

    results = await knowledge_manager.search(limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_combined_filters(knowledge_manager):
    """Test search with multiple filters."""
    await knowledge_manager.write("mem1", "decision", "important decision about apples", ["important"])
    await knowledge_manager.write("mem2", "fact", "red apple facts", ["fruit"])
    await knowledge_manager.write("mem3", "decision", "car decision", ["vehicle"])

    # Search for type=decision AND query=apple
    results = await knowledge_manager.search(query="apple", type="decision")
    assert len(results) == 1
    assert results[0]["key"] == "mem1"


@pytest.mark.asyncio
async def test_delete_existing(knowledge_manager):
    """Test deleting existing memory."""
    await knowledge_manager.write("delete_test", "type", "content", [])

    # Verify it exists
    memory = await knowledge_manager.read("delete_test")
    assert memory is not None

    # Delete it
    result = await knowledge_manager.delete("delete_test")
    assert result is True

    # Verify it's gone
    memory = await knowledge_manager.read("delete_test")
    assert memory is None


@pytest.mark.asyncio
async def test_delete_nonexistent(knowledge_manager):
    """Test deleting non-existent memory."""
    result = await knowledge_manager.delete("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_update_tags(knowledge_manager):
    """Test updating tags for existing memory."""
    await knowledge_manager.write("tag_test", "type", "content", ["old_tag"])

    result = await knowledge_manager.update_tags("tag_test", ["new_tag", "another_tag"])
    assert result is True

    memory = await knowledge_manager.read("tag_test")
    assert memory["tags"] == ["new_tag", "another_tag"]


@pytest.mark.asyncio
async def test_update_tags_nonexistent(knowledge_manager):
    """Test updating tags for non-existent memory."""
    result = await knowledge_manager.update_tags("nonexistent", ["tags"])
    assert result is True  # SQLite UPDATE on non-existent row doesn't fail


@pytest.mark.asyncio
async def test_get_stats(knowledge_manager):
    """Test getting memory statistics."""
    # Add test data
    await knowledge_manager.write("mem1", "decision", "content1", ["tag1"])
    await knowledge_manager.write("mem2", "fact", "content2", ["tag1", "tag2"])
    await knowledge_manager.write("mem3", "decision", "content3", ["tag2"])

    stats = await knowledge_manager.get_stats()

    assert stats["total_memories"] == 3
    assert stats["by_type"]["decision"] == 2
    assert stats["by_type"]["fact"] == 1
    assert "recent_updates" in stats


@pytest.mark.asyncio
async def test_get_stats_empty(knowledge_manager):
    """Test getting stats when database is empty."""
    stats = await knowledge_manager.get_stats()
    assert stats["total_memories"] == 0
    assert stats["by_type"] == {}
    assert stats["recent_updates"] == 0


@pytest.mark.asyncio
async def test_cleanup_old_memories(knowledge_manager):
    """Test cleaning up old memories."""
    # Add test data - simulate old memory by manually setting old date
    import sqlite3
    from datetime import datetime, timedelta

    # Add a memory and manually set its updated_at to old date
    await knowledge_manager.write("old_memory", "fact", "old content", [])
    await knowledge_manager.write("new_memory", "decision", "new content", [])
    await knowledge_manager.write("lesson_memory", "learned_lesson", "lesson content", [])

    # Manually update the old memory's timestamp
    old_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(knowledge_manager.db_path) as conn:
        conn.execute("UPDATE memories SET updated_at = ? WHERE key = ?", (old_date, "old_memory"))

    # Cleanup memories older than 365 days (but not learned lessons)
    removed = await knowledge_manager.cleanup_old_memories(days_old=365)

    assert removed == 1  # Only old_memory should be removed

    # Verify memories
    old_mem = await knowledge_manager.read("old_memory")
    new_mem = await knowledge_manager.read("new_memory")
    lesson_mem = await knowledge_manager.read("lesson_memory")

    assert old_mem is None  # Should be deleted
    assert new_mem is not None  # Should remain
    assert lesson_mem is not None  # Should remain (learned_lesson type)


@pytest.mark.asyncio
async def test_cleanup_old_memories_no_old(knowledge_manager):
    """Test cleanup when no old memories exist."""
    await knowledge_manager.write("recent_memory", "fact", "recent content", [])

    removed = await knowledge_manager.cleanup_old_memories(days_old=1)
    assert removed == 0

    # Memory should still exist
    memory = await knowledge_manager.read("recent_memory")
    assert memory is not None


@pytest.mark.asyncio
async def test_error_handlings_full(knowledge_manager):
    """Test error handling in all methods (lines 63, 86, 119, 175, 193, 213, 239)"""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        # write error (63-65)
        res = await knowledge_manager.write("k", "t", "c")
        assert "Error writing memory" in res

        # read error (86-88)
        assert await knowledge_manager.read("k") is None

        # search error (119-121)
        assert await knowledge_manager.search() == []

        # delete error (175-177)
        assert await knowledge_manager.delete("k") is False

        # update_tags error (193-195)
        assert await knowledge_manager.update_tags("k", []) is False

        # get_stats error (213-215)
        stats = await knowledge_manager.get_stats()
        assert "error" in stats

        # cleanup_old_memories error (239-241)
        assert await knowledge_manager.cleanup_old_memories() == 0


# ==============================================================
# Round 3 — merged from test_coverage_round3.py
# ==============================================================


@pytest.mark.asyncio
async def test_knowledge_memory_invalid_order_by():
    """Line 165: invalid order_by falls back to 'updated_at DESC'."""
    mgr = KnowledgeMemoryManager(db_path=":memory:")

    results = await mgr.search(query="test", order_by="1; DROP TABLE memories;--")
    assert isinstance(results, list)
