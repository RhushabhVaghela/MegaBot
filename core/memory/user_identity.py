import asyncio
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("megabot.memory.identity")


class UserIdentityManager:
    """Manages user identity linking across platforms."""

    def __init__(
        self,
        db_path: str,
        executor: ThreadPoolExecutor | None = None,
    ):
        self.db_path = db_path
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="identity_db")
        self._local = threading.local()
        self._init_tables()

    def _init_tables(self):
        """Initialize user identity tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_identities (
                    internal_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    platform_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (platform, platform_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_internal_id ON user_identities(internal_id)")
            # idx_platform is redundant — platform is the leading column of the
            # composite PRIMARY KEY (platform, platform_id), which already serves
            # as an index for platform-only lookups.

    def _get_connection(self):
        """Get thread-local database connection with WAL mode enabled."""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s on lock
        return self._local.conn

    def close(self):
        """Close the thread-local database connection if it exists."""
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            except Exception as e:
                logger.debug("Error closing user_identity DB connection: %s", e)

    async def link_identity(self, internal_id: str, platform: str, platform_id: str) -> bool:
        """Link a platform-specific ID to a unified internal ID."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor,
                self._sync_link_identity,
                internal_id,
                platform,
                platform_id,
            )
            logger.info(f"Linked {platform}:{platform_id} to internal ID: {internal_id}")
            return True
        except Exception as e:
            logger.error(f"Error linking identity: {e}")
            return False

    def _sync_link_identity(self, internal_id: str, platform: str, platform_id: str):
        """Synchronous link identity operation."""
        conn = self._get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO user_identities (internal_id, platform, platform_id) VALUES (?, ?, ?)",
            (internal_id, platform, platform_id),
        )
        conn.commit()

    async def get_unified_id(self, platform: str, platform_id: str) -> str:
        """Get the unified internal ID for a platform identity. Returns platform_id if not linked."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_unified_id, platform, platform_id)
        except Exception as e:
            logger.error(f"Error retrieving unified ID: {e}")
            return platform_id

    def _sync_get_unified_id(self, platform: str, platform_id: str) -> str:
        """Synchronous get unified ID operation."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT internal_id FROM user_identities WHERE platform = ? AND platform_id = ?",
            (platform, platform_id),
        )
        row = cursor.fetchone()
        return row[0] if row else platform_id

    async def get_platform_ids(self, internal_id: str) -> list:
        """Get all platform IDs linked to an internal ID."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_platform_ids, internal_id)
        except Exception as e:
            logger.error(f"Error retrieving platform IDs for {internal_id}: {e}")
            return []

    def _sync_get_platform_ids(self, internal_id: str) -> list:
        """Synchronous get platform IDs operation."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT platform, platform_id FROM user_identities WHERE internal_id = ?",
            (internal_id,),
        )
        return [{"platform": r[0], "platform_id": r[1]} for r in cursor.fetchall()]

    async def unlink_identity(self, platform: str, platform_id: str) -> bool:
        """Remove the link for a platform identity."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_unlink_identity, platform, platform_id)
        except Exception as e:
            logger.error(f"Error unlinking identity: {e}")
            return False

    def _sync_unlink_identity(self, platform: str, platform_id: str) -> bool:
        """Synchronous unlink identity operation."""
        conn = self._get_connection()
        cursor = conn.execute(
            "DELETE FROM user_identities WHERE platform = ? AND platform_id = ?",
            (platform, platform_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def get_identity_stats(self) -> dict:
        """Get statistics about identity linking."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_identity_stats)
        except Exception as e:
            logger.error(f"Error getting identity stats: {e}")
            return {"error": str(e)}

    def _sync_get_identity_stats(self) -> dict:
        """Synchronous get identity stats operation."""
        conn = self._get_connection()
        total_links = conn.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0]
        platforms = conn.execute("SELECT platform, COUNT(*) FROM user_identities GROUP BY platform").fetchall()
        return {
            "total_links": total_links,
            "by_platform": dict(platforms),
        }
