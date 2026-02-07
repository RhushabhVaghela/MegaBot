import sys
import os
from typing import Any
from core.interfaces import MemoryInterface
from core.resource_guard import LRUCache


class MemUAdapter(MemoryInterface):
    def __init__(self, memu_path: str, db_url: str):
        service_class = None
        # 1. Try checking if it's already installed as a package (Docker entrypoint handles this)
        try:
            from memu.app import MemoryService  # type: ignore

            print("Successfully loaded memU from installed packages")
            service_class = MemoryService
            found_path = True
        except ImportError:
            # 2. Try finding the package in likely locations
            possible_paths = [
                os.path.join(memu_path, "src"),
                memu_path,
                os.path.join(memu_path, "memu"),
            ]

            found_path = False
            for path in possible_paths:
                if os.path.exists(path):
                    sys.path.insert(0, path)
                    try:
                        from memu.app import MemoryService  # type: ignore # pragma: no cover

                        self.memu_path = path  # pragma: no cover
                        service_class = MemoryService
                        found_path = True  # pragma: no cover
                        print(f"Successfully loaded memU from {path}")  # pragma: no cover
                        break  # pragma: no cover
                    except ImportError:
                        sys.path.pop(0)
                        continue

        if not found_path:
            print(f"WARNING: memU not found at {memu_path}. Using functional fallback mock.")

            # Fallback Mock Class with basic functional storage
            class MockMemoryService:
                def __init__(self, **kwargs):
                    self.storage: LRUCache[str, Any] = LRUCache(maxsize=2048)

                async def memorize(self, **kwargs):
                    content = kwargs.get("content")
                    url = kwargs.get("resource_url")
                    key = url or f"item_{len(self.storage)}"
                    self.storage[key] = content or "File/Link"
                    print(f"MockMemory: Stored {key}")

                async def retrieve(self, **kwargs):
                    query = kwargs.get("query", "").lower()
                    items = [
                        {"content": v, "id": k}
                        for k, v in self.storage.items()
                        if query in str(v).lower() or query in str(k).lower()
                    ]
                    return {"items": items}

            service_class = MockMemoryService
            found_path = True

        if service_class:
            try:
                self.service = service_class(
                    llm_profiles={
                        "default": {
                            "provider": "ollama",
                            "api_key": "local",
                            "chat_model": "llama3",
                            "base_url": "http://127.0.0.1:11434/v1",
                        }
                    },
                    database_config={
                        "metadata_store": {
                            "provider": "sqlite",
                            "connection_url": db_url,
                        },
                        "vector_store": {
                            "provider": "sqlite",
                            "connection_url": db_url,
                        },
                    },
                )
            except Exception as e:
                print(f"Failed to initialize MemoryService: {e}")

                # Final fallback to ultra-safe dummy
                class Dummy:
                    async def memorize(self, **kwargs):
                        pass

                    async def retrieve(self, **kwargs):
                        return {"items": []}

                self.service = Dummy()
        else:  # pragma: no cover
            # Final fallback to ultra-safe dummy if no service_class found (should not happen due to mock)
            class Dummy:
                async def memorize(self, **kwargs):
                    pass

                async def retrieve(self, **kwargs):
                    return {"items": []}

            self.service = Dummy()

    async def store(self, key: str, value: Any) -> None:
        # Auto-detect modality
        modality = "document"
        ext = os.path.splitext(key)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".gif"]:
            modality = "image"
        elif ext in [".mp4", ".mov", ".avi"]:
            modality = "video"
        elif ext in [".mp3", ".wav", ".m4a"]:
            modality = "audio"

        is_path = os.path.exists(key) or key.startswith("http")

        await self.service.memorize(
            resource_url=key if is_path else None,
            content=str(value) if not is_path else None,
            modality=modality,
        )

    async def get_anticipations(self) -> list[dict]:
        # Query memU for proactive triggers
        # This is a specialized semantic search for tasks/needs
        results = await self.service.retrieve(
            query="What are the user's upcoming needs or proactive tasks based on context?",
            method="llm",  # Deep semantic reasoning mode
        )
        if isinstance(results, dict):
            return results.get("items", [])
        return []

    async def ingest_openclaw_logs(self, log_path: str):
        if not os.path.exists(log_path):
            print(f"OpenClaw logs not found at {log_path}")
            return

        # memU can process conversation logs
        await self.service.memorize(resource_url=log_path, modality="conversation")
        print(f"Ingested OpenClaw logs from {log_path}")

    async def retrieve(self, key: str) -> Any:
        return await self.service.retrieve(query=key)

    async def get_proactive_suggestions(self) -> list[dict]:
        """Get proactive suggestions based on memory patterns."""
        try:
            results = await self.service.retrieve(
                query="What proactive actions or reminders should be suggested based on user patterns and current context?",
                method="llm",
                limit=5,
            )
            if isinstance(results, dict):
                return results.get("items", [])
        except Exception as e:
            print(f"Proactive retrieval failed: {e}")
        return []

    async def learn_from_interaction(self, interaction_data: dict):
        """Learn from user interactions to improve future suggestions."""
        content = f"User interaction: {interaction_data.get('action', 'unknown')} at {interaction_data.get('timestamp', 'now')}"
        if "context" in interaction_data:
            content += f" Context: {interaction_data['context']}"

        await self.service.memorize(
            content=content,
            modality="interaction",
            metadata={"type": "learning", "interaction": interaction_data},
        )

    async def search(self, query: str) -> list[Any]:
        """Search for memories matching the query."""
        try:
            results = await self.service.retrieve(query=query, method="semantic", limit=10)
            if isinstance(results, dict):
                return results.get("items", [])
        except Exception as e:
            print(f"Search failed: {e}")
        return []
