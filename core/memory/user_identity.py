import sqlite3
import logging
import asyncio

logger = logging.getLogger("megabot.memory.identity")


class UserIdentityManager:
    """Manages user identity linking across platforms."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Initialize user identity tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "PRAGMA journal_mode=WAL"
            )  # Enable WAL mode for better concurrency
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_identities (
                    internal_id TEXT,
                    platform TEXT,
                    platform_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (platform, platform_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_internal_id ON user_identities(internal_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_platform ON user_identities(platform)"
            )

    async def link_identity(
        self, internal_id: str, platform: str, platform_id: str
    ) -> bool:
        """Link a platform-specific ID to a unified internal ID."""
        try:
            await asyncio.to_thread(
                self._sync_link_identity, internal_id, platform, platform_id
            )
            logger.info(
                f"Linked {platform}:{platform_id} to internal ID: {internal_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Error linking identity: {e}")
            return False

    def _sync_link_identity(self, internal_id: str, platform: str, platform_id: str):
        """Synchronous link identity operation."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_identities (internal_id, platform, platform_id) VALUES (?, ?, ?)",
                (internal_id, platform, platform_id),
            )

    async def get_unified_id(self, platform: str, platform_id: str) -> str:
        """Get the unified internal ID for a platform identity. Returns platform_id if not linked."""
        try:
            return await asyncio.to_thread(
                self._sync_get_unified_id, platform, platform_id
            )
        except Exception as e:
            logger.error(f"Error retrieving unified ID: {e}")
            return platform_id

    def _sync_get_unified_id(self, platform: str, platform_id: str) -> str:
        """Synchronous get unified ID operation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT internal_id FROM user_identities WHERE platform = ? AND platform_id = ?",
                (platform, platform_id),
            )
            row = cursor.fetchone()
            return row[0] if row else platform_id

    async def get_platform_ids(self, internal_id: str) -> list:
        """Get all platform IDs linked to an internal ID."""
        try:
            return await asyncio.to_thread(self._sync_get_platform_ids, internal_id)
        except Exception as e:
            logger.error(f"Error retrieving platform IDs for {internal_id}: {e}")
            return []

    def _sync_get_platform_ids(self, internal_id: str) -> list:
        """Synchronous get platform IDs operation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT platform, platform_id FROM user_identities WHERE internal_id = ?",
                (internal_id,),
            )
            return [{"platform": r[0], "platform_id": r[1]} for r in cursor.fetchall()]

    async def unlink_identity(self, platform: str, platform_id: str) -> bool:
        """Remove the link for a platform identity."""
        try:
            return await asyncio.to_thread(
                self._sync_unlink_identity, platform, platform_id
            )
        except Exception as e:
            logger.error(f"Error unlinking identity: {e}")
            return False

    def _sync_unlink_identity(self, platform: str, platform_id: str) -> bool:
        """Synchronous unlink identity operation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM user_identities WHERE platform = ? AND platform_id = ?",
                (platform, platform_id),
            )
            return cursor.rowcount > 0

    async def get_identity_stats(self) -> dict:
        """Get statistics about identity linking."""
        try:
            return await asyncio.to_thread(self._sync_get_identity_stats)
        except Exception as e:
            logger.error(f"Error getting identity stats: {e}")
            return {"error": str(e)}

    def _sync_get_identity_stats(self) -> dict:
        """Synchronous get identity stats operation."""
        with sqlite3.connect(self.db_path) as conn:
            total_links = conn.execute(
                "SELECT COUNT(*) FROM user_identities"
            ).fetchone()[0]
            platforms = conn.execute(
                "SELECT platform, COUNT(*) FROM user_identities GROUP BY platform"
            ).fetchall()
            return {
                "total_links": total_links,
                "by_platform": dict(platforms),
            }
