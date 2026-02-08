import asyncio
import logging
import os
import sqlite3
import zlib
from datetime import datetime

from cryptography.fernet import Fernet  # type: ignore

logger = logging.getLogger("megabot.memory.backup")


class MemoryBackupManager:
    """Handles database backup and restore operations with encryption and compression.

    All heavy I/O (file reads, sqlite operations, compression) is offloaded
    to a worker thread via ``asyncio.to_thread`` so the event loop is never
    blocked.
    """

    def __init__(self, db_path: str, backup_dir: str | None = None):
        self.db_path = db_path
        self.backup_dir = backup_dir or os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Sync helpers (run inside worker threads)
    # ------------------------------------------------------------------

    def _create_backup_sync(self, encryption_key: str | None = None) -> str:
        """Blocking implementation of backup creation."""
        temp_db = f"{self.db_path}.tmp"
        try:
            key = encryption_key or os.environ.get("MEGABOT_BACKUP_KEY")
            if not key:
                return "Error: No encryption key provided or found in environment."

            fernet = Fernet(key.encode() if isinstance(key, str) else key)

            # 1. Use SQLite backup API to get a consistent snapshot (WAL-safe)
            source_conn = sqlite3.connect(self.db_path)
            dest_conn = sqlite3.connect(temp_db)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                source_conn.close()

            # 2. Read and compress
            with open(temp_db, "rb") as f:
                data = f.read()

            compressed_data = zlib.compress(data)
            encrypted_data = fernet.encrypt(compressed_data)

            # 3. Save to backup dir
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(self.backup_dir, f"memory_backup_{timestamp}.enc")

            with open(backup_file, "wb") as f:
                f.write(encrypted_data)

            logger.info("Database backup created: %s", backup_file)
            return f"Backup created successfully: {os.path.basename(backup_file)}"
        except Exception as e:
            logger.error("Backup failed: %s", e)
            return f"Error: Backup failed: {e}"
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except OSError as e:
                    logger.debug("Failed to remove temp DB %s during backup cleanup: %s", temp_db, e)

    def _restore_backup_sync(self, backup_file: str, encryption_key: str | None = None) -> str:
        """Blocking implementation of backup restore."""
        temp_db = f"{self.db_path}.restored"
        try:
            key = encryption_key or os.environ.get("MEGABOT_BACKUP_KEY")
            if not key:
                return "Error: No encryption key provided or found in environment."

            fernet = Fernet(key.encode() if isinstance(key, str) else key)

            # 1. Read and decrypt backup
            backup_path = os.path.join(self.backup_dir, backup_file)
            if not os.path.exists(backup_path):
                return f"Error: Backup file not found: {backup_file}"

            with open(backup_path, "rb") as f:
                encrypted_data = f.read()

            decrypted_data = fernet.decrypt(encrypted_data)
            decompressed_data = zlib.decompress(decrypted_data)

            # 2. Create temporary restored database
            with open(temp_db, "wb") as f:
                f.write(decompressed_data)

            # 3. Validate the restored database
            try:
                with sqlite3.connect(temp_db) as conn:
                    conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                    conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()
                    conn.execute("SELECT COUNT(*) FROM user_identities").fetchone()
            except Exception as e:
                os.remove(temp_db)
                return f"Error: Restored database is corrupted: {e}"

            # 4. Replace current database atomically
            # Strategy: rename current → .bak, then rename restored → current.
            # os.replace() is atomic on POSIX when source and dest are on the
            # same filesystem.
            backup_current = f"{self.db_path}.bak"
            try:
                # Remove WAL/SHM files for the current DB before swap
                for suffix in ("-wal", "-shm"):
                    wal_path = self.db_path + suffix
                    if os.path.exists(wal_path):
                        os.remove(wal_path)

                os.replace(self.db_path, backup_current)
            except FileNotFoundError:
                # No existing DB to back up — first run or already gone
                pass

            try:
                os.replace(temp_db, self.db_path)
            except Exception:
                # Critical: restored file failed to move into place.
                # Attempt to recover from .bak so we don't lose the DB.
                if os.path.exists(backup_current) and not os.path.exists(self.db_path):
                    os.replace(backup_current, self.db_path)
                    logger.error("Restore swap failed — recovered original database from .bak")
                raise

            logger.info("Database restored from backup: %s", backup_file)
            return f"Database restored successfully from {backup_file}. Previous database backed up as .bak"
        except Exception as e:
            logger.error("Restore failed: %s", e)
            return f"Error: Restore failed: {e}"
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except OSError as e:
                    logger.debug("Failed to remove temp DB %s during restore cleanup: %s", temp_db, e)

    def _list_backups_sync(self) -> list:
        """Blocking implementation of backup listing."""
        try:
            if not os.path.exists(self.backup_dir):
                return []

            files = []
            for filename in os.listdir(self.backup_dir):
                if filename.startswith("memory_backup_") and filename.endswith(".enc"):
                    filepath = os.path.join(self.backup_dir, filename)
                    stat = os.stat(filepath)
                    files.append(
                        {
                            "filename": filename,
                            "size": stat.st_size,
                            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        }
                    )
            return sorted(files, key=lambda x: x["created"], reverse=True)
        except Exception as e:
            logger.error("Error listing backups: %s", e)
            return []

    def _cleanup_old_backups_sync(self, keep_days: int = 30) -> int:
        """Blocking implementation of old backup cleanup."""
        try:
            cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)
            removed_count = 0

            for filename in os.listdir(self.backup_dir):
                if filename.startswith("memory_backup_") and filename.endswith(".enc"):
                    filepath = os.path.join(self.backup_dir, filename)
                    if os.path.getctime(filepath) < cutoff_time:
                        os.remove(filepath)
                        removed_count += 1
                        logger.info("Removed old backup: %s", filename)

            return removed_count
        except Exception as e:
            logger.error("Error cleaning up old backups: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Async public API (offloads to worker thread)
    # ------------------------------------------------------------------

    async def create_backup(self, encryption_key: str | None = None) -> str:
        """Create a compressed and encrypted backup of the memory database."""
        return await asyncio.to_thread(self._create_backup_sync, encryption_key)

    async def restore_backup(self, backup_file: str, encryption_key: str | None = None) -> str:
        """Restore database from an encrypted backup."""
        return await asyncio.to_thread(self._restore_backup_sync, backup_file, encryption_key)

    async def list_backups(self) -> list:
        """List all available backup files."""
        return await asyncio.to_thread(self._list_backups_sync)

    async def cleanup_old_backups(self, keep_days: int = 30) -> int:
        """Remove backup files older than specified days."""
        return await asyncio.to_thread(self._cleanup_old_backups_sync, keep_days)

    async def get_backup_stats(self) -> dict:
        """Get statistics about backup files."""
        try:
            backups = await self.list_backups()
            if not backups:
                return {
                    "total_backups": 0,
                    "total_size": 0,
                    "oldest": None,
                    "newest": None,
                }

            total_size = sum(b["size"] for b in backups)
            return {
                "total_backups": len(backups),
                "total_size": total_size,
                "oldest": backups[-1]["created"] if backups else None,
                "newest": backups[0]["created"] if backups else None,
            }
        except Exception as e:
            logger.error("Error getting backup stats: %s", e)
            return {"error": str(e)}
