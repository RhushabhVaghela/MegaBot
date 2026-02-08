import pytest
import os
import sqlite3
import tempfile
from core.memory.user_identity import UserIdentityManager


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
def identity_manager(temp_db):
    """Create UserIdentityManager instance."""
    return UserIdentityManager(temp_db)


@pytest.mark.asyncio
async def test_init(identity_manager, temp_db):
    """Test UserIdentityManager initialization."""
    assert identity_manager.db_path == temp_db
    # Verify tables were created
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "user_identities" in tables

        # Check indexes
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_internal_id" in indexes
        # idx_platform was removed — platform is the leading column of the
        # composite PRIMARY KEY (platform, platform_id), which already
        # serves as an index for platform-only lookups.


@pytest.mark.asyncio
async def test_link_identity_success(identity_manager):
    """Test successful identity linking."""
    result = await identity_manager.link_identity("internal_123", "discord", "user_456")
    assert result is True

    # Verify the link was created
    unified_id = await identity_manager.get_unified_id("discord", "user_456")
    assert unified_id == "internal_123"


@pytest.mark.asyncio
async def test_link_identity_replace_existing(identity_manager):
    """Test linking replaces existing identity."""
    # Link initially
    await identity_manager.link_identity("internal_123", "discord", "user_456")

    # Link to different internal ID
    result = await identity_manager.link_identity("internal_789", "discord", "user_456")
    assert result is True

    # Verify it was replaced
    unified_id = await identity_manager.get_unified_id("discord", "user_456")
    assert unified_id == "internal_789"


@pytest.mark.asyncio
async def test_get_unified_id_existing(identity_manager):
    """Test getting unified ID for linked identity."""
    await identity_manager.link_identity("internal_123", "discord", "user_456")

    result = await identity_manager.get_unified_id("discord", "user_456")
    assert result == "internal_123"


@pytest.mark.asyncio
async def test_get_unified_id_nonexistent(identity_manager):
    """Test getting unified ID for unlinked identity returns platform_id."""
    result = await identity_manager.get_unified_id("discord", "user_456")
    assert result == "user_456"


@pytest.mark.asyncio
async def test_get_platform_ids(identity_manager):
    """Test getting all platform IDs for an internal ID."""
    # Link multiple platforms to same internal ID
    await identity_manager.link_identity("internal_123", "discord", "user_456")
    await identity_manager.link_identity("internal_123", "telegram", "tg_user_789")
    await identity_manager.link_identity("internal_123", "slack", "slack_user_101")

    platform_ids = await identity_manager.get_platform_ids("internal_123")

    expected = [
        {"platform": "discord", "platform_id": "user_456"},
        {"platform": "telegram", "platform_id": "tg_user_789"},
        {"platform": "slack", "platform_id": "slack_user_101"},
    ]
    # Sort both lists for comparison since order might vary
    platform_ids.sort(key=lambda x: x["platform"])
    expected.sort(key=lambda x: x["platform"])
    assert platform_ids == expected


@pytest.mark.asyncio
async def test_get_platform_ids_no_links(identity_manager):
    """Test getting platform IDs for internal ID with no links."""
    platform_ids = await identity_manager.get_platform_ids("nonexistent")
    assert platform_ids == []


@pytest.mark.asyncio
async def test_unlink_identity_existing(identity_manager):
    """Test unlinking existing identity."""
    await identity_manager.link_identity("internal_123", "discord", "user_456")

    # Verify it exists
    unified_id = await identity_manager.get_unified_id("discord", "user_456")
    assert unified_id == "internal_123"

    # Unlink it
    result = await identity_manager.unlink_identity("discord", "user_456")
    assert result is True

    # Verify it's gone
    unified_id = await identity_manager.get_unified_id("discord", "user_456")
    assert unified_id == "user_456"  # Falls back to platform_id


@pytest.mark.asyncio
async def test_unlink_identity_nonexistent(identity_manager):
    """Test unlinking non-existent identity."""
    result = await identity_manager.unlink_identity("discord", "nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_get_identity_stats(identity_manager):
    """Test getting identity statistics."""
    # Add some test data
    await identity_manager.link_identity("internal_1", "discord", "user_1")
    await identity_manager.link_identity("internal_1", "telegram", "tg_user_1")
    await identity_manager.link_identity("internal_2", "discord", "user_2")
    await identity_manager.link_identity("internal_2", "slack", "slack_user_2")

    stats = await identity_manager.get_identity_stats()

    assert stats["total_links"] == 4
    assert stats["by_platform"]["discord"] == 2
    assert stats["by_platform"]["telegram"] == 1
    assert stats["by_platform"]["slack"] == 1


@pytest.mark.asyncio
async def test_get_identity_stats_empty(identity_manager):
    """Test getting stats when database is empty."""
    stats = await identity_manager.get_identity_stats()
    assert stats["total_links"] == 0
    assert stats["by_platform"] == {}


@pytest.mark.asyncio
async def test_multiple_platforms_same_internal_id(identity_manager):
    """Test multiple platforms linked to same internal ID."""
    internal_id = "user_123"

    # Link multiple platforms
    await identity_manager.link_identity(internal_id, "discord", "discord_123")
    await identity_manager.link_identity(internal_id, "telegram", "telegram_123")
    await identity_manager.link_identity(internal_id, "slack", "slack_123")

    # Verify all return the same unified ID
    assert await identity_manager.get_unified_id("discord", "discord_123") == internal_id
    assert await identity_manager.get_unified_id("telegram", "telegram_123") == internal_id
    assert await identity_manager.get_unified_id("slack", "slack_123") == internal_id

    # Verify platform IDs are returned correctly
    platform_ids = await identity_manager.get_platform_ids(internal_id)
    assert len(platform_ids) == 3
    platforms = [p["platform"] for p in platform_ids]
    assert "discord" in platforms
    assert "telegram" in platforms
    assert "slack" in platforms


@pytest.mark.asyncio
async def test_same_platform_different_users(identity_manager):
    """Test different users on same platform."""
    await identity_manager.link_identity("internal_1", "discord", "user_1")
    await identity_manager.link_identity("internal_2", "discord", "user_2")

    assert await identity_manager.get_unified_id("discord", "user_1") == "internal_1"
    assert await identity_manager.get_unified_id("discord", "user_2") == "internal_2"


@pytest.mark.asyncio
async def test_link_identity_error_handling(identity_manager):
    """Test error handling in link_identity."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await identity_manager.link_identity("internal_123", "discord", "user_456")
        assert result is False


@pytest.mark.asyncio
async def test_get_unified_id_error_handling(identity_manager):
    """Test error handling in get_unified_id."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await identity_manager.get_unified_id("discord", "user_456")
        assert result == "user_456"  # Should return platform_id on error


@pytest.mark.asyncio
async def test_get_platform_ids_error_handling(identity_manager):
    """Test error handling in get_platform_ids."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await identity_manager.get_platform_ids("internal_123")
        assert result == []


@pytest.mark.asyncio
async def test_unlink_identity_error_handling(identity_manager):
    """Test error handling in unlink_identity."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await identity_manager.unlink_identity("discord", "user_456")
        assert result is False


@pytest.mark.asyncio
async def test_get_identity_stats_error_handling(identity_manager):
    """Test error handling in get_identity_stats."""
    import unittest.mock

    with unittest.mock.patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("DB Error")

        result = await identity_manager.get_identity_stats()
        assert result == {"error": "DB Error"}
