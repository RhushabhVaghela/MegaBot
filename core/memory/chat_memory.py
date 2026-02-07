import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("megabot.memory.chat")


class ChatMemoryManager:
    """Manages chat history operations with optimized queries and indexing."""

    def __init__(self, db_path: str, executor=None):
        self.db_path = db_path
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
        self._local = threading.local()  # Thread-local storage for connections
        self._init_tables()

    def _init_tables(self):
        """Initialize chat history tables and indexes."""
        conn = self._get_connection()
        conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for better concurrency
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                metadata TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Composite index for the primary query pattern: WHERE chat_id = ? ORDER BY timestamp DESC
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_id_timestamp ON chat_history(chat_id, timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_platform ON chat_history(platform)")
        conn.commit()

    def _get_connection(self):
        """Get a thread-local database connection."""
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
            except Exception:
                pass

    async def write(
        self,
        chat_id: str,
        platform: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Store a message in the chat history."""
        try:
            metadata_json = json.dumps(metadata or {})
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor,
                self._sync_write,
                chat_id,
                platform,
                role,
                content,
                metadata_json,
            )
            return True
        except Exception as e:
            logger.error(f"Error writing chat history: {e}")
            return False

    def _sync_write(self, chat_id: str, platform: str, role: str, content: str, metadata_json: str):
        """Synchronous write operation."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO chat_history (chat_id, platform, role, content, metadata)
            VALUES (?, ?, ?, ?, ?)
        """,
            (chat_id, platform, role, content, metadata_json),
        )
        conn.commit()

    async def read(self, chat_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve recent chat history for a specific context."""
        try:
            loop = asyncio.get_running_loop()
            rows = await loop.run_in_executor(self._executor, self._sync_read, chat_id, limit)
            # Reverse to get chronological order
            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "metadata": json.loads(r[2] or "{}"),
                    "timestamp": r[3],
                }
                for r in reversed(rows)
            ]
        except Exception as e:
            logger.error(f"Error reading chat history for {chat_id}: {e}")
            return []

    def _sync_read(self, chat_id: str, limit: int):
        """Synchronous read operation."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT role, content, metadata, timestamp FROM chat_history
            WHERE chat_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (chat_id, limit),
        )
        return cursor.fetchall()

    async def forget(self, chat_id: str, max_history: int = 500) -> bool:
        """
        'Forget' or clean up old chat history for a specific chat_id.
        If history exceeds max_history, delete the oldest entries,
        EXCLUDING messages tagged with 'keep_forever'.
        """
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_forget, chat_id, max_history)
        except Exception as e:
            logger.error(f"Error cleaning chat history for {chat_id}: {e}")
            return False

    def _sync_forget(self, chat_id: str, max_history: int) -> bool:
        """Synchronous forget operation."""
        conn = self._get_connection()
        # Count current messages that are NOT keep_forever
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM chat_history
            WHERE chat_id = ?
            AND (metadata IS NULL OR metadata NOT LIKE '%"keep_forever": true%')
            """,
            (chat_id,),
        )
        count = cursor.fetchone()[0]

        if count > max_history:
            to_delete = count - max_history
            logger.info(f"Cleaning up {to_delete} old messages for {chat_id}")
            conn.execute(
                """
                DELETE FROM chat_history
                WHERE id IN (
                    SELECT id FROM chat_history
                    WHERE chat_id = ?
                    AND (metadata IS NULL OR metadata NOT LIKE '%"keep_forever": true%')
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
            """,
                (chat_id, to_delete),
            )
            conn.commit()
            return True
        return False

    async def get_all_chat_ids(self) -> List[str]:
        """Retrieve all unique chat_ids from history."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_all_chat_ids)
        except Exception as e:
            logger.error(f"Error getting chat IDs: {e}")
            return []

    def _sync_get_all_chat_ids(self) -> List[str]:
        """Synchronous get all chat IDs operation."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT DISTINCT chat_id FROM chat_history")
        return [r[0] for r in cursor.fetchall()]

    async def get_chat_stats(self, chat_id: str) -> Dict[str, Any]:
        """Get statistics for a specific chat."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_chat_stats, chat_id)
        except Exception as e:
            logger.error(f"Error getting chat stats for {chat_id}: {e}")
            return {"error": str(e)}

    def _sync_get_chat_stats(self, chat_id: str) -> Dict[str, Any]:
        """Synchronous get chat stats operation."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM chat_history WHERE chat_id = ?",
            (chat_id,),
        )
        count, oldest, newest = cursor.fetchone()
        return {
            "chat_id": chat_id,
            "message_count": count,
            "oldest_message": oldest,
            "newest_message": newest,
        }

    async def get_aggregate_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all chats."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_aggregate_stats)
        except Exception as e:
            logger.error(f"Error getting aggregate chat stats: {e}")
            return {"error": str(e)}

    def _sync_get_aggregate_stats(self) -> Dict[str, Any]:
        """Synchronous aggregate stats operation."""
        conn = self._get_connection()
        total = conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
        unique_chats = conn.execute("SELECT COUNT(DISTINCT chat_id) FROM chat_history").fetchone()[0]
        platforms = conn.execute("SELECT platform, COUNT(*) FROM chat_history GROUP BY platform").fetchall()
        recent = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE timestamp >= datetime('now', '-7 days')"
        ).fetchone()[0]
        return {
            "total_messages": total,
            "unique_chats": unique_chats,
            "by_platform": dict(platforms),
            "recent_messages_7d": recent,
        }
