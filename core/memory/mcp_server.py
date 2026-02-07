import os
import logging
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from .chat_memory import ChatMemoryManager
from .user_identity import UserIdentityManager
from .knowledge_memory import KnowledgeMemoryManager
from .backup_manager import MemoryBackupManager

logger = logging.getLogger("megabot.memory")


class MemoryServer:
    """
    Persistent cross-session knowledge system for MegaBot.
    Acts as an internal MCP server for memory management.
    Now uses modular components for better maintainability.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Store in the project root by default
            db_path = os.path.join(os.getcwd(), "megabot_memory.db")
        self.db_path = db_path

        # Shared executor for all memory managers to avoid over-subscribing threads
        self._shared_executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="mem-db"
        )

        # Initialize modular managers with shared executor
        self.chat_memory = ChatMemoryManager(db_path, executor=self._shared_executor)
        self.user_identity = UserIdentityManager(db_path)
        self.knowledge_memory = KnowledgeMemoryManager(
            db_path, executor=self._shared_executor
        )
        self.backup_manager = MemoryBackupManager(db_path)

        logger.info(f"Memory database initialized at {self.db_path}")

    # Chat History Methods (delegated to ChatMemoryManager)
    async def chat_write(
        self,
        chat_id: str,
        platform: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Store a message in the chat history."""
        return await self.chat_memory.write(chat_id, platform, role, content, metadata)

    async def chat_read(self, chat_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve recent chat history for a specific context."""
        return await self.chat_memory.read(chat_id, limit)

    async def chat_forget(self, chat_id: str, max_history: int = 500) -> bool:
        """Clean up old chat history for a specific chat_id."""
        return await self.chat_memory.forget(chat_id, max_history)

    async def get_all_chat_ids(self) -> List[str]:
        """Retrieve all unique chat_ids from history."""
        return await self.chat_memory.get_all_chat_ids()

    # User Identity Methods (delegated to UserIdentityManager)
    async def link_identity(
        self, internal_id: str, platform: str, platform_id: str
    ) -> bool:
        """Link a platform-specific ID to a unified internal ID."""
        return await self.user_identity.link_identity(
            internal_id, platform, platform_id
        )

    async def get_unified_id(self, platform: str, platform_id: str) -> str:
        """Get the unified internal ID for a platform identity."""
        return await self.user_identity.get_unified_id(platform, platform_id)

    # Knowledge Memory Methods (delegated to KnowledgeMemoryManager)
    async def memory_write(
        self, key: str, type: str, content: str, tags: Optional[List[str]] = None
    ) -> str:
        """Record new knowledge or decisions."""
        return await self.knowledge_memory.write(key, type, content, tags)

    async def memory_read(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve specific memory content by key."""
        return await self.knowledge_memory.read(key)

    async def memory_search(
        self,
        query: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        order_by: str = "updated_at DESC",
    ) -> List[Dict[str, Any]]:
        """Search for memories by query, type, or tags."""
        return await self.knowledge_memory.search(query, type, tags, limit, order_by)

    # Backup Methods (delegated to MemoryBackupManager)
    async def backup_database(self, encryption_key: Optional[str] = None) -> str:
        """Create a compressed and encrypted backup of the memory database."""
        return await self.backup_manager.create_backup(encryption_key)

    # Stats Methods (aggregated from all managers)
    async def memory_stats(self) -> Dict[str, Any]:
        """View analytics on memory usage across all components."""
        try:
            chat_stats = await self.chat_memory.get_chat_stats(
                "dummy"
            )  # Get general stats
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
    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Any:
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
