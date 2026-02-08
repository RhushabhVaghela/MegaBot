import asyncio
import concurrent.futures
import json
import logging
import sqlite3
import threading
from typing import Any

logger = logging.getLogger("megabot.memory.knowledge")

# Whitelist of allowed ORDER BY clauses to prevent SQL injection
_ALLOWED_ORDER_BY = frozenset(
    {
        "updated_at DESC",
        "updated_at ASC",
        "created_at DESC",
        "created_at ASC",
        "key DESC",
        "key ASC",
        "type DESC",
        "type ASC",
    }
)


class KnowledgeMemoryManager:
    """Manages general knowledge and learned lessons with advanced search capabilities."""

    def __init__(
        self,
        db_path: str,
        executor: concurrent.futures.ThreadPoolExecutor | None = None,
    ):
        self.db_path = db_path
        # Accept a shared executor or create a private one
        self._executor = executor or concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="knowledge_db"
        )
        self._local = threading.local()
        self._init_tables()

    def _init_tables(self):
        """Initialize knowledge memory tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for better concurrency
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    type TEXT,
                    content TEXT,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(type)")
            # idx_key is intentionally omitted — 'key' is the PRIMARY KEY, which
            # already has an implicit unique B-tree index in SQLite.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tags ON memories(tags)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_updated_at ON memories(updated_at)")

    def _get_connection(self):
        """Get thread-local database connection."""
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
                logger.debug("Error closing knowledge_memory DB connection: %s", e)

    async def write(self, key: str, type: str, content: str, tags: list[str] | None = None) -> str:
        """Record new knowledge or decisions."""
        tags_json = json.dumps(tags or [])
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(self._executor, self._sync_write, key, type, content, tags_json)
            return result
        except Exception as e:
            logger.error(f"Error writing memory: {e}")
            return f"Error writing memory: {e}"

    def _sync_write(self, key: str, type: str, content: str, tags_json: str) -> str:
        """Synchronous write operation."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO memories (key, type, content, tags, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
            (key, type, content, tags_json),
        )
        conn.commit()
        return "Memory written successfully"

    async def read(self, key: str) -> dict[str, Any] | None:
        """Retrieve specific memory content by key."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_read, key)
        except Exception as e:
            logger.error(f"Error reading memory '{key}': {e}")
            return None

    def _sync_read(self, key: str) -> dict[str, Any] | None:
        """Synchronous read operation."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM memories WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return {
                "key": row[0],
                "type": row[1],
                "content": row[2],
                "tags": json.loads(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
        return None

    async def search(
        self,
        query: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
        order_by: str = "updated_at DESC",
    ) -> list[dict[str, Any]]:
        """Search for memories by query, type, or tags with advanced filtering."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_search, query, type, tags, limit, order_by)
        except Exception as e:
            logger.error(f"Error searching memories: {e}")
            return []

    def _sync_search(
        self,
        query: str | None,
        type: str | None,
        tags: list[str] | None,
        limit: int | None,
        order_by: str,
    ) -> list[dict[str, Any]]:
        """Synchronous search operation."""
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list = []

        if query:
            sql += " AND (content LIKE ? OR key LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])

        if type:
            sql += " AND type = ?"
            params.append(type)

        # Push tag filtering into SQL using JSON string matching.
        # Tags are stored as JSON arrays like '["foo", "bar"]', so
        # matching LIKE '%"tagname"%' is reliable and avoids fetching
        # all rows into Python for post-hoc filtering.
        if tags:
            for tag in tags:
                sql += " AND tags LIKE ?"
                params.append(f'%"{tag}"%')

        # Validate order_by against whitelist to prevent SQL injection
        if order_by not in _ALLOWED_ORDER_BY:
            order_by = "updated_at DESC"

        sql += f" ORDER BY {order_by}"

        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        results = []
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            results.append(
                {
                    "key": row[0],
                    "type": row[1],
                    "content": row[2],
                    "tags": json.loads(row[3]),
                    "created_at": row[4],
                    "updated_at": row[5],
                }
            )
        return results

    async def delete(self, key: str) -> bool:
        """Delete a memory by key."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_delete, key)
        except Exception as e:
            logger.error(f"Error deleting memory '{key}': {e}")
            return False

    def _sync_delete(self, key: str) -> bool:
        """Synchronous delete operation."""
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0

    async def update_tags(self, key: str, tags: list[str]) -> bool:
        """Update tags for an existing memory."""
        tags_json = json.dumps(tags)
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_update_tags, key, tags_json)
        except Exception as e:
            logger.error(f"Error updating tags for memory '{key}': {e}")
            return False

    def _sync_update_tags(self, key: str, tags_json: str) -> bool:
        """Synchronous update tags operation."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE memories SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
            (tags_json, key),
        )
        conn.commit()
        return True

    async def get_stats(self) -> dict[str, Any]:
        """View analytics on memory usage."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_stats)
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return {"error": str(e)}

    def _sync_get_stats(self) -> dict[str, Any]:
        """Synchronous get stats operation."""
        conn = self._get_connection()
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        types = conn.execute("SELECT type, COUNT(*) FROM memories GROUP BY type").fetchall()
        recent = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE updated_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
        return {
            "total_memories": total,
            "by_type": dict(types),
            "recent_updates": recent,
        }

    async def cleanup_old_memories(self, days_old: int = 365) -> int:
        """Remove memories older than specified days (except critical ones)."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_cleanup_old_memories, days_old)
        except Exception as e:
            logger.error(f"Error cleaning up old memories: {e}")
            return 0

    def _sync_cleanup_old_memories(self, days_old: int) -> int:
        """Synchronous cleanup operation."""
        conn = self._get_connection()
        # Use parameterized query to prevent SQL injection
        # (days_old is cast to int for defense-in-depth even though type-hinted)
        cursor = conn.execute(
            """
            DELETE FROM memories
            WHERE updated_at < datetime('now', ?)
            AND type != 'learned_lesson'
            """,
            (f"-{int(days_old)} days",),
        )
        conn.commit()
        return cursor.rowcount
