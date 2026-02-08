from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.memu_adapter import MemUAdapter


@pytest.fixture
def mock_memory_service():
    mock_service_class = MagicMock()
    mock_instance = MagicMock()
    mock_service_class.return_value = mock_instance
    with patch.dict("sys.modules", {"memu.app": MagicMock(MemoryService=mock_service_class)}):
        yield mock_instance


@pytest.mark.asyncio
async def test_memu_adapter_store(mock_memory_service):
    with patch("adapters.memu_adapter.os.path.exists", return_value=False):
        adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")
        adapter.service.memorize = AsyncMock()
        await adapter.store("key1", "value1")
        assert adapter.service.memorize.called


@pytest.mark.asyncio
async def test_memu_adapter_search(mock_memory_service):
    adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")
    adapter.service.retrieve = AsyncMock(return_value={"items": [{"content": "found it"}]})
    results = await adapter.search("query")
    assert results == [{"content": "found it"}]


@pytest.mark.asyncio
async def test_memu_adapter_retrieve(mock_memory_service):
    adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")
    adapter.service.retrieve = AsyncMock(return_value="data")
    res = await adapter.retrieve("key")
    assert res == "data"


@pytest.mark.asyncio
async def test_memu_adapter_ingest_logs(mock_memory_service, tmp_path):
    log_file = tmp_path / "sessions.jsonl"
    log_file.write_text("{}")
    adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")
    adapter.service.memorize = AsyncMock()
    await adapter.ingest_openclaw_logs(str(log_file))
    assert adapter.service.memorize.called


@pytest.mark.asyncio
async def test_memu_adapter_ingest_logs_not_found(mock_memory_service):
    adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")
    await adapter.ingest_openclaw_logs("/non/existent/path")
    assert True


@pytest.mark.asyncio
async def test_memu_adapter_fallback_mock():
    """Test that the adapter falls back to a functional mock if memu is missing"""
    with (
        patch("adapters.memu_adapter.os.path.exists", return_value=False),
        # Ensure imports fail
        patch.dict("sys.modules", {"memu.app": None}),
    ):
        adapter = MemUAdapter("/nonexistent", "sqlite://")

        # Test storage in mock
        await adapter.store("test.txt", "content")
        res = await adapter.search("content")
        assert len(res) == 1
        assert res[0]["content"] == "content"


@pytest.mark.asyncio
async def test_memu_adapter_anticipations(mock_memory_service):
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.retrieve = AsyncMock(return_value={"items": [{"content": "task1"}]})
    res = await adapter.get_anticipations()
    assert res == [{"content": "task1"}]


@pytest.mark.asyncio
async def test_memu_adapter_anticipations_none(mock_memory_service):
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.retrieve = AsyncMock(return_value=None)
    res = await adapter.get_anticipations()
    assert res == []


@pytest.mark.asyncio
async def test_memu_adapter_store_multimodal(mock_memory_service):
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.memorize = AsyncMock()
    await adapter.store("image.png", b"data")
    args = adapter.service.memorize.call_args[1]
    assert args["modality"] == "image"
    await adapter.store("audio.mp3", b"data")
    args = adapter.service.memorize.call_args[1]
    assert args["modality"] == "audio"


@pytest.mark.asyncio
async def test_memu_adapter_path_search_success():
    """Test that memU path is set when found via file system search"""
    # Track import attempts
    import_attempts = []

    def mock_import(name, *args, **kwargs):
        import_attempts.append(name)
        if name == "memu.app":
            if len(import_attempts) == 1:
                # First attempt (installed package) fails
                raise ImportError("No module named 'memu.app'")
            else:
                # Second attempt (from path) succeeds
                mock_module = MagicMock()
                mock_service_class = MagicMock()
                mock_module.MemoryService = mock_service_class
                return mock_module
        return __import__(name, *args, **kwargs)

    # Mock path existence - first path exists
    with patch("adapters.memu_adapter.os.path.exists") as mock_exists:
        mock_exists.side_effect = lambda p: p == "/tmp/mock_memu/src"

        with patch("builtins.__import__", side_effect=mock_import):
            adapter = MemUAdapter("/tmp/mock_memu", "sqlite:///:memory:")

            # Verify that memu_path was set to the found path
            assert hasattr(adapter, "memu_path")
            assert adapter.memu_path == "/tmp/mock_memu/src"


@pytest.mark.asyncio
async def test_memu_adapter_failed_initialization():
    """Test fallback when MemoryService initialization fails"""
    mock_service_class = MagicMock()
    mock_service_class.side_effect = Exception("Init failed")

    with patch.dict("sys.modules", {"memu.app": MagicMock(MemoryService=mock_service_class)}):
        adapter = MemUAdapter("/tmp", "sqlite://")

        # Should have fallen back to Dummy service
        result = await adapter.retrieve("key")
        assert result == {"items": []}

        # Store should not crash
        await adapter.store("key", "value")


@pytest.mark.asyncio
async def test_memu_adapter_import_error_handling():
    """Test import error handling in path search loop"""
    import sys

    with patch("adapters.memu_adapter.os.path.exists", return_value=True), patch("sys.path", []):
        # Remove memu.app from sys.modules if it exists
        original_module = sys.modules.pop("memu.app", None)
        try:
            adapter = MemUAdapter("/tmp/test_memu", "sqlite:///:memory:")
            # Should fall back to mock when import fails
            assert adapter is not None
            # Verify it's using the fallback
            result = await adapter.retrieve("key")
            assert result == {"items": []}
        finally:
            if original_module:
                sys.modules["memu.app"] = original_module


@pytest.mark.asyncio
async def test_memu_adapter_store_video_modality(mock_memory_service):
    """Test storing video files detects video modality"""
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.memorize = AsyncMock()
    await adapter.store("video.mp4", b"video_data")
    args = adapter.service.memorize.call_args[1]
    assert args["modality"] == "video"


@pytest.mark.asyncio
async def test_memu_adapter_get_proactive_suggestions(mock_memory_service):
    """Test get_proactive_suggestions method"""
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.retrieve = AsyncMock(return_value={"items": [{"content": "suggestion"}]})
    result = await adapter.get_proactive_suggestions()
    assert result == [{"content": "suggestion"}]


@pytest.mark.asyncio
async def test_memu_adapter_get_proactive_suggestions_exception(mock_memory_service):
    """Test get_proactive_suggestions exception handling"""
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.retrieve = AsyncMock(side_effect=Exception("Retrieval failed"))
    result = await adapter.get_proactive_suggestions()
    assert result == []


@pytest.mark.asyncio
async def test_memu_adapter_learn_from_interaction(mock_memory_service):
    """Test learn_from_interaction method"""
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.memorize = AsyncMock()

    interaction_data = {
        "action": "clicked_button",
        "timestamp": "2024-01-01T12:00:00",
        "context": "dashboard",
    }

    await adapter.learn_from_interaction(interaction_data)

    # Verify memorize was called with correct content
    call_args = adapter.service.memorize.call_args
    assert call_args is not None
    kwargs = call_args[1]
    assert "User interaction: clicked_button at 2024-01-01T12:00:00" in kwargs["content"]
    assert "Context: dashboard" in kwargs["content"]
    assert kwargs["modality"] == "interaction"


@pytest.mark.asyncio
async def test_memu_adapter_search_exception(mock_memory_service):
    """Test search method exception handling"""
    adapter = MemUAdapter("/tmp", "sqlite://")
    adapter.service.retrieve = AsyncMock(side_effect=Exception("Search failed"))
    result = await adapter.search("query")
    assert result == []


# =====================================================================
# Phase 6B-7: _make_dummy_service() tests
# =====================================================================


def test_make_dummy_service_returns_object_with_async_methods():
    """_make_dummy_service() returns an object with memorize() and retrieve() methods."""
    dummy = MemUAdapter._make_dummy_service()
    assert hasattr(dummy, "memorize")
    assert hasattr(dummy, "retrieve")
    assert callable(dummy.memorize)
    assert callable(dummy.retrieve)


@pytest.mark.asyncio
async def test_make_dummy_service_memorize_returns_none():
    """Dummy memorize() accepts kwargs and returns None."""
    dummy = MemUAdapter._make_dummy_service()
    result = await dummy.memorize(content="test", modality="text")
    assert result is None


@pytest.mark.asyncio
async def test_make_dummy_service_retrieve_returns_empty_items():
    """Dummy retrieve() accepts kwargs and returns {"items": []}."""
    dummy = MemUAdapter._make_dummy_service()
    result = await dummy.retrieve(query="anything", limit=10)
    assert result == {"items": []}
