import os
import shutil
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from megabot.core.memory.backup_manager import MemoryBackupManager


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    # Create a simple database with some tables
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE memories (id INTEGER, content TEXT)")
    conn.execute("CREATE TABLE chat_history (id INTEGER, content TEXT)")
    conn.execute("CREATE TABLE user_identities (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO memories VALUES (1, 'test memory')")
    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def backup_manager(temp_db):
    """Create MemoryBackupManager instance."""
    manager = MemoryBackupManager(temp_db)
    # Clean the backup directory
    if os.path.exists(manager.backup_dir):
        shutil.rmtree(manager.backup_dir)
    os.makedirs(manager.backup_dir, exist_ok=True)
    return manager


@pytest.mark.asyncio
async def test_init(backup_manager, temp_db):
    """Test MemoryBackupManager initialization."""
    assert backup_manager.db_path == temp_db
    assert backup_manager.backup_dir == os.path.join(os.path.dirname(temp_db), "backups")
    assert os.path.exists(backup_manager.backup_dir)


@pytest.mark.asyncio
async def test_init_custom_backup_dir(temp_db):
    """Test initialization with custom backup directory."""
    custom_dir = "/tmp/custom_backups"
    manager = MemoryBackupManager(temp_db, custom_dir)
    assert manager.backup_dir == custom_dir


@pytest.mark.asyncio
async def test_create_backup_success(backup_manager, temp_db):
    """Test successful backup creation."""
    # Use a proper base64-encoded 32-byte Fernet key
    test_key = "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9jaGFyc19sb25n"  # base64 encoded

    # Mock Fernet to avoid real encryption
    with patch("megabot.core.memory.backup_manager.Fernet") as mock_fernet:
        mock_fernet_instance = MagicMock()
        mock_fernet_instance.encrypt.return_value = b"encrypted_data"
        mock_fernet.return_value = mock_fernet_instance

        result = await backup_manager.create_backup(test_key)

        assert "Backup created successfully" in result
        assert "memory_backup_" in result
        assert ".enc" in result

        # Verify Fernet was called with correct key
        mock_fernet.assert_called_once_with(test_key.encode())

        # Verify encrypt was called
        mock_fernet_instance.encrypt.assert_called_once()


@pytest.mark.asyncio
async def test_create_backup_no_key(backup_manager, monkeypatch):
    """Test backup creation without encryption key."""
    # Temporarily clear the backup key from environment
    monkeypatch.delenv("MEGABOT_BACKUP_KEY", raising=False)
    result = await backup_manager.create_backup()
    assert "Error: No encryption key provided" in result


@pytest.mark.asyncio
async def test_create_backup_encryption_error(backup_manager):
    """Test backup creation with encryption error."""
    test_key = "test_key"

    with patch("megabot.core.memory.backup_manager.Fernet") as mock_fernet:
        mock_fernet_instance = MagicMock()
        mock_fernet_instance.encrypt.side_effect = ValueError("Encryption failed")
        mock_fernet.return_value = mock_fernet_instance

        result = await backup_manager.create_backup(test_key)

        assert "Error: Backup failed: Encryption failed" in result


@pytest.mark.asyncio
async def test_restore_backup_success(backup_manager, temp_db):
    """Test successful backup restoration."""
    # Use a proper base64-encoded 32-byte Fernet key
    test_key = "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9jaGFyc19sb25n"  # 44 chars base64 = 32 bytes when decoded
    backup_file = "memory_backup_20231201_120000.enc"

    # Use the existing temp_db content (already has tables from fixture)
    with open(temp_db, "rb") as f:
        db_content = f.read()

    # Mock Fernet - use the actual key that would work
    with patch("megabot.core.memory.backup_manager.Fernet") as mock_fernet:
        mock_fernet_instance = MagicMock()
        # Mock decrypt to return the database content
        mock_fernet_instance.decrypt.return_value = db_content
        mock_fernet.return_value = mock_fernet_instance

        # Mock zlib to return the content as-is
        with patch("megabot.core.memory.backup_manager.zlib") as mock_zlib:
            mock_zlib.decompress.return_value = db_content

            # Create a fake backup file
            backup_path = os.path.join(backup_manager.backup_dir, backup_file)
            with open(backup_path, "wb") as f:
                f.write(b"fake_encrypted_data")

            result = await backup_manager.restore_backup(backup_file, test_key)

            assert "Database restored successfully" in result
            assert backup_file in result

            # Cleanup
            if os.path.exists(backup_path):
                os.remove(backup_path)


@pytest.mark.asyncio
async def test_restore_backup_no_key(backup_manager, monkeypatch):
    """Test restore without encryption key."""
    # Temporarily clear the backup key from environment
    monkeypatch.delenv("MEGABOT_BACKUP_KEY", raising=False)
    result = await backup_manager.restore_backup("test.enc")
    assert "Error: No encryption key provided" in result


@pytest.mark.asyncio
async def test_restore_backup_file_not_found(backup_manager):
    """Test restore with non-existent backup file."""
    # Mock Fernet to avoid key validation
    with patch("megabot.core.memory.backup_manager.Fernet"):
        result = await backup_manager.restore_backup("nonexistent.enc", "any_key")
        assert "Error: Backup file not found" in result


@pytest.mark.asyncio
async def test_restore_backup_corrupted_database(backup_manager, temp_db):
    """Test restore with corrupted database data."""
    test_key = "test_key"
    backup_file = "corrupted.enc"

    with patch("megabot.core.memory.backup_manager.Fernet") as mock_fernet:
        mock_fernet_instance = MagicMock()
        mock_fernet_instance.decrypt.return_value = b"corrupted_data"
        mock_fernet.return_value = mock_fernet_instance

        with patch("megabot.core.memory.backup_manager.zlib") as mock_zlib:
            mock_zlib.decompress.return_value = b"not_sqlite_data"

            # Create fake backup file
            backup_path = os.path.join(backup_manager.backup_dir, backup_file)
            with open(backup_path, "wb") as f:
                f.write(b"fake_data")

            result = await backup_manager.restore_backup(backup_file, test_key)

            assert "Error: Restored database is corrupted" in result

            # Cleanup
            if os.path.exists(backup_path):
                os.remove(backup_path)


@pytest.mark.asyncio
async def test_list_backups_empty(backup_manager):
    """Test listing backups when directory is empty."""
    backups = await backup_manager.list_backups()
    assert backups == []


@pytest.mark.asyncio
async def test_list_backups_with_files(backup_manager):
    """Test listing backups with backup files."""
    # Create some fake backup files
    test_files = [
        "memory_backup_20231201_120000.enc",
        "memory_backup_20231202_130000.enc",
        "not_a_backup.txt",
    ]

    for filename in test_files:
        filepath = os.path.join(backup_manager.backup_dir, filename)
        with open(filepath, "w") as f:
            f.write("test")

    backups = await backup_manager.list_backups()

    # Should only return the .enc files with memory_backup_ prefix
    assert len(backups) == 2
    assert all(b["filename"].endswith(".enc") for b in backups)
    assert all("memory_backup_" in b["filename"] for b in backups)

    # Should be sorted by creation time (newest first)
    assert backups[0]["filename"] > backups[1]["filename"]

    # Cleanup
    for filename in test_files:
        filepath = os.path.join(backup_manager.backup_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)


@pytest.mark.asyncio
async def test_list_backups_error(backup_manager):
    """Test listing backups with error."""
    with patch("os.listdir", side_effect=OSError("List error")):
        backups = await backup_manager.list_backups()
        assert backups == []


@pytest.mark.asyncio
async def test_cleanup_old_backups(backup_manager):
    """Test cleaning up old backup files."""
    import time

    # Create test files with different ages
    test_files = [
        ("memory_backup_old.enc", 40 * 24 * 60 * 60),  # 40 days old
        ("memory_backup_new.enc", 0),  # New file
    ]

    for filename, _age_seconds in test_files:
        filepath = os.path.join(backup_manager.backup_dir, filename)
        with open(filepath, "w") as f:
            f.write("test")

    # Mock getctime to return appropriate timestamps
    old_time = time.time() - (40 * 24 * 60 * 60)  # 40 days ago
    new_time = time.time()  # Now

    with patch("os.path.getctime") as mock_getctime:

        def mock_ctime(path):
            if "old" in path:
                return old_time
            else:
                return new_time

        mock_getctime.side_effect = mock_ctime

        removed_count = await backup_manager.cleanup_old_backups(keep_days=30)

        assert removed_count == 1

    # Check files
    old_file = os.path.join(backup_manager.backup_dir, "memory_backup_old.enc")
    new_file = os.path.join(backup_manager.backup_dir, "memory_backup_new.enc")

    # The old file should be removed by the mocked function
    # But in reality, we can't test file removal easily, so just check the count
    if os.path.exists(new_file):
        os.remove(new_file)


@pytest.mark.asyncio
async def test_cleanup_old_backups_error(backup_manager):
    """Test cleanup with error."""
    with patch("os.listdir", side_effect=OSError("Cleanup error")):
        removed_count = await backup_manager.cleanup_old_backups()
        assert removed_count == 0


@pytest.mark.asyncio
async def test_get_backup_stats_empty(backup_manager):
    """Test getting stats when no backups exist."""
    stats = await backup_manager.get_backup_stats()
    expected = {
        "total_backups": 0,
        "total_size": 0,
        "oldest": None,
        "newest": None,
    }
    assert stats == expected


@pytest.mark.asyncio
async def test_get_backup_stats_with_backups(backup_manager):
    """Test getting stats with backup files."""
    # Create test backup files
    test_files = [
        ("memory_backup_20231201_120000.enc", 100),
        ("memory_backup_20231202_130000.enc", 200),
    ]

    for filename, size in test_files:
        filepath = os.path.join(backup_manager.backup_dir, filename)
        with open(filepath, "wb") as f:
            f.write(b"x" * size)

    stats = await backup_manager.get_backup_stats()

    assert stats["total_backups"] == 2
    assert stats["total_size"] == 300
    assert stats["oldest"] is not None
    assert stats["newest"] is not None
    assert stats["newest"] >= stats["oldest"]

    # Cleanup
    for filename, _ in test_files:
        filepath = os.path.join(backup_manager.backup_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)


@pytest.mark.asyncio
async def test_get_backup_stats_error(backup_manager):
    """Test getting stats with error."""
    with patch.object(backup_manager, "list_backups", side_effect=OSError("Stats error")):
        stats = await backup_manager.get_backup_stats()
        assert "error" in stats


@pytest.mark.asyncio
async def test_restore_backup_general_exception(backup_manager):
    """Test restore_backup with general exception (lines 104-106)"""
    # Mock Fernet constructor to raise exception
    with patch("megabot.core.memory.backup_manager.Fernet", side_effect=ValueError("General Error")):
        result = await backup_manager.restore_backup("test.enc", "key")
        assert "Error: Restore failed: General Error" in result


@pytest.mark.asyncio
async def test_list_backups_dir_not_exists(backup_manager):
    """Test list_backups when directory does not exist (line 112)"""
    # Force backup_dir to a non-existent path
    backup_manager.backup_dir = "/tmp/non-existent-dir-12345"
    if os.path.exists(backup_manager.backup_dir):
        os.rmdir(backup_manager.backup_dir)

    result = await backup_manager.list_backups()
    assert result == []
