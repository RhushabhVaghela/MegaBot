import logging
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .backup_manager import MemoryBackupManager
from .chat_memory import ChatMemoryManager
from .knowledge_memory import KnowledgeMemoryManager
from .user_identity import UserIdentityManager

logger = logging.getLogger("megabot.memory")

# Schema version — bump this when you add migrations below.
_SCHEMA_VERSION = 1


class MemoryServer:
    """
    Persistent cross-session knowledge system for MegaBot.
    Acts as an internal MCP server for memory management.
    Now uses modular components for better maintainability.
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            # Store in the project root by default
            db_path = os.path.join(os.getcwd(), "megabot_memory.db")
        self.db_path = db_path

        # Run schema migrations before initializing managers
        self._run_migrations()

        # Shared executor for all memory managers to avoid over-subscribing threads
        self._shared_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mem-db")

        # Initialize modular managers with shared executor
        self.chat_memory = ChatMemoryManager(db_path, executor=self._shared_executor)
        self.user_identity = UserIdentityManager(db_path, executor=self._shared_executor)
        self.knowledge_memory = KnowledgeMemoryManager(db_path, executor=self._shared_executor)
        self.backup_manager = MemoryBackupManager(db_path)

        logger.info(f"Memory database initialized at {self.db_path}")

    # ------------------------------------------------------------------
    # Schema migration infrastructure
    # ------------------------------------------------------------------
    def _run_migrations(self):
        """Apply schema migrations up to _SCHEMA_VERSION."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] if row[0] is not None else 0

            # --- Migration 1: initial schema baseline ----------------------
            if current < 1:
                # Tables are created by individual managers via CREATE IF NOT EXISTS,
                # so migration 1 just records the baseline.
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (1,))
                logger.info("Schema migration 1 applied (baseline)")

            # --- Add future migrations here as `if current < N:` blocks ----

            conn.commit()
        except Exception as e:
            logger.error(f"Schema migration failed: {e}")
            raise
        finally:
            conn.close()

    async def close(self):
        """Shut down the shared thread pool and close DB connections."""
        self.chat_memory.close()
        self.knowledge_memory.close()
        self.user_identity.close()
        self._shared_executor.shutdown(wait=False)
        logger.info("Memory server shut down")

    # Chat History Methods (delegated to ChatMemoryManager)
    async def chat_write(
        self,
        chat_id: str,
        platform: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store a message in the chat history."""
        return await self.chat_memory.write(chat_id, platform, role, content, metadata)

    async def chat_read(self, chat_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent chat history for a specific context."""
        return await self.chat_memory.read(chat_id, limit)

    async def chat_forget(self, chat_id: str, max_history: int = 500) -> bool:
        """Clean up old chat history for a specific chat_id."""
        return await self.chat_memory.forget(chat_id, max_history)

    async def get_all_chat_ids(self) -> list[str]:
        """Retrieve all unique chat_ids from history."""
        return await self.chat_memory.get_all_chat_ids()

    # User Identity Methods (delegated to UserIdentityManager)
    async def link_identity(self, internal_id: str, platform: str, platform_id: str) -> bool:
        """Link a platform-specific ID to a unified internal ID."""
        return await self.user_identity.link_identity(internal_id, platform, platform_id)

    async def get_unified_id(self, platform: str, platform_id: str) -> str:
        """Get the unified internal ID for a platform identity."""
        return await self.user_identity.get_unified_id(platform, platform_id)

    # Knowledge Memory Methods (delegated to KnowledgeMemoryManager)
    async def memory_write(self, key: str, type: str, content: str, tags: list[str] | None = None) -> str:
        """Record new knowledge or decisions."""
        return await self.knowledge_memory.write(key, type, content, tags)

    async def memory_read(self, key: str) -> dict[str, Any] | None:
        """Retrieve specific memory content by key."""
        return await self.knowledge_memory.read(key)

    async def memory_search(
        self,
        query: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
        order_by: str = "updated_at DESC",
    ) -> list[dict[str, Any]]:
        """Search for memories by query, type, or tags."""
        return await self.knowledge_memory.search(query, type, tags, limit, order_by)

    # Backup Methods (delegated to MemoryBackupManager)
    async def backup_database(self, encryption_key: str | None = None) -> str:
        """Create a compressed and encrypted backup of the memory database."""
        return await self.backup_manager.create_backup(encryption_key)

    # Stats Methods (aggregated from all managers)
    async def memory_stats(self) -> dict[str, Any]:
        """View analytics on memory usage across all components."""
        try:
            chat_stats = await self.chat_memory.get_aggregate_stats()
            identity_stats = await self.user_identity.get_identity_stats()
            knowledge_stats = await self.knowledge_memory.get_stats()
            backup_stats = await self.backup_manager.get_backup_stats()

            return {
                "chat": chat_stats,
                "identities": identity_stats,
                "knowledge": knowledge_stats,
                "backups": backup_stats,
                "db_path": self.db_path,
            }
        except Exception as e:
            return {"error": str(e)}

    # MCP Tool Dispatcher (updated to delegate to managers)
    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Dispatcher for MCP-style tool calls."""
        # Chat memory tools
        if name == "chat_write":
            return await self.chat_write(**arguments)
        elif name == "chat_read":
            return await self.chat_read(**arguments)
        elif name == "chat_forget":
            return await self.chat_forget(**arguments)

        # Knowledge memory tools
        elif name == "memory_write":
            return await self.memory_write(**arguments)
        elif name == "memory_read":
            return await self.memory_read(**arguments)
        elif name == "memory_search":
            return await self.memory_search(**arguments)

        # Identity tools
        elif name == "link_identity":
            return await self.link_identity(**arguments)
        elif name == "get_unified_id":
            return await self.get_unified_id(**arguments)

        # Backup tools
        elif name == "backup_database":
            return await self.backup_database(**arguments)

        # Stats tools
        elif name == "memory_stats":
            return await self.memory_stats()

        else:
            raise ValueError(f"Unknown memory tool: {name}")
