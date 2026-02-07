"""Tests for core/resource_guard.py — LRUCache, ResourceSnapshot, helpers, ResourceGuard."""

import asyncio
from collections import namedtuple
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from core.resource_guard import (
    LRUCache,
    ResourceGuard,
    ResourceSnapshot,
    RAM_BUFFER_MB,
    VRAM_BUFFER_MB,
    _query_vram,
    can_allocate,
    get_resource_status,
)


# ---------------------------------------------------------------------------
# LRUCache
# ---------------------------------------------------------------------------


class TestLRUCache:
    """Tests for the bounded LRU cache."""

    def test_init_default_maxsize(self):
        cache = LRUCache()
        assert cache.maxsize == 1024
        assert len(cache) == 0

    def test_init_custom_maxsize(self):
        cache = LRUCache(maxsize=5)
        assert cache.maxsize == 5

    def test_init_invalid_maxsize_zero(self):
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            LRUCache(maxsize=0)

    def test_init_invalid_maxsize_negative(self):
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            LRUCache(maxsize=-1)

    def test_setitem_getitem(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        assert cache["a"] == 1

    def test_getitem_missing_raises_keyerror(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        with pytest.raises(KeyError):
            _ = cache["missing"]

    def test_contains(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["x"] = 42
        assert "x" in cache
        assert "y" not in cache

    def test_len(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        assert len(cache) == 0
        cache["a"] = 1
        cache["b"] = 2
        assert len(cache) == 2

    def test_delitem(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        del cache["a"]
        assert "a" not in cache
        assert len(cache) == 0

    def test_delitem_missing_raises_keyerror(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        with pytest.raises(KeyError):
            del cache["nope"]

    def test_get_existing(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        assert cache.get("a") == 1

    def test_get_missing_default(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        assert cache.get("nope") is None
        assert cache.get("nope", 99) == 99

    def test_pop_existing(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        val = cache.pop("a")
        assert val == 1
        assert "a" not in cache

    def test_pop_missing_with_default(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        assert cache.pop("nope", 42) == 42

    def test_pop_missing_no_default_raises(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        with pytest.raises(KeyError):
            cache.pop("nope")

    def test_keys_values_items(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        cache["b"] = 2
        assert set(cache.keys()) == {"a", "b"}
        assert set(cache.values()) == {1, 2}
        assert set(cache.items()) == {("a", 1), ("b", 2)}

    def test_clear(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=10)
        cache["a"] = 1
        cache["b"] = 2
        cache.clear()
        assert len(cache) == 0
        assert "a" not in cache

    def test_repr(self):
        cache: LRUCache[str, int] = LRUCache(maxsize=5)
        cache["a"] = 1
        assert repr(cache) == "LRUCache(maxsize=5, size=1)"

    def test_eviction_at_maxsize(self):
        """When full, the LRU (oldest untouched) entry is evicted."""
        cache: LRUCache[str, int] = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        # Full — inserting "d" should evict "a"
        cache["d"] = 4
        assert len(cache) == 3
        assert "a" not in cache
        assert list(cache.keys()) == ["b", "c", "d"]

    def test_eviction_respects_access_order(self):
        """Accessing an entry makes it most-recently-used, so it's not evicted."""
        cache: LRUCache[str, int] = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        # Access "a" — now "b" is LRU
        _ = cache["a"]
        cache["d"] = 4
        assert "a" in cache
        assert "b" not in cache  # "b" was LRU

    def test_update_existing_key_moves_to_end(self):
        """Updating an existing key should move it to most-recently-used."""
        cache: LRUCache[str, int] = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        # Update "a" — now "b" is LRU
        cache["a"] = 10
        cache["d"] = 4
        assert "a" in cache
        assert cache["a"] == 10
        assert "b" not in cache

    def test_maxsize_1(self):
        """Edge case: cache with maxsize=1 always holds the last set item."""
        cache: LRUCache[str, int] = LRUCache(maxsize=1)
        cache["a"] = 1
        assert cache["a"] == 1
        cache["b"] = 2
        assert "a" not in cache
        assert cache["b"] == 2
        assert len(cache) == 1

    def test_get_promotes_to_mru(self):
        """.get() should also promote the entry to most-recently-used."""
        cache: LRUCache[str, int] = LRUCache(maxsize=3)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        cache.get("a")  # promote "a"
        cache["d"] = 4  # evicts "b" (LRU)
        assert "a" in cache
        assert "b" not in cache


# ---------------------------------------------------------------------------
# ResourceSnapshot
# ---------------------------------------------------------------------------


class TestResourceSnapshot:
    """Tests for ResourceSnapshot dataclass and properties."""

    def test_ram_headroom_positive(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=20000,
            ram_available_mb=12000,
            ram_percent=62.5,
        )
        # headroom = 12000 - 3072 = 8928
        assert snap.ram_headroom_mb == 12000 - RAM_BUFFER_MB

    def test_ram_headroom_zero_when_below_buffer(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=30000,
            ram_available_mb=2000,  # less than 3072 buffer
            ram_percent=93.75,
        )
        assert snap.ram_headroom_mb == 0.0

    def test_ram_headroom_exactly_at_buffer(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=32000 - RAM_BUFFER_MB,
            ram_available_mb=float(RAM_BUFFER_MB),
            ram_percent=90.0,
        )
        assert snap.ram_headroom_mb == 0.0

    def test_vram_headroom_none_when_no_vram(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
        )
        assert snap.vram_headroom_mb is None

    def test_vram_headroom_positive(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
            vram_total_mb=16000,
            vram_used_mb=8000,
            vram_available_mb=8000,
        )
        assert snap.vram_headroom_mb == 8000 - VRAM_BUFFER_MB

    def test_vram_headroom_zero_when_below_buffer(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
            vram_total_mb=16000,
            vram_used_mb=15000,
            vram_available_mb=1000,  # less than 2048 buffer
        )
        assert snap.vram_headroom_mb == 0.0

    def test_timestamp_auto_set(self):
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
        )
        assert snap.timestamp > 0


# ---------------------------------------------------------------------------
# _query_vram
# ---------------------------------------------------------------------------


class TestQueryVram:
    """Tests for the nvidia-smi helper."""

    @patch("core.resource_guard.subprocess.run")
    def test_successful_query(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="16384, 8192, 8192\n",
        )
        result = _query_vram()
        assert result == {"total": 16384.0, "used": 8192.0, "free": 8192.0}

    @patch("core.resource_guard.subprocess.run")
    def test_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _query_vram() is None

    @patch("core.resource_guard.subprocess.run")
    def test_exception_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
        assert _query_vram() is None

    @patch("core.resource_guard.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        import subprocess as sp

        mock_run.side_effect = sp.TimeoutExpired(cmd="nvidia-smi", timeout=5)
        assert _query_vram() is None

    @patch("core.resource_guard.subprocess.run")
    def test_malformed_output_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="garbage")
        assert _query_vram() is None


# ---------------------------------------------------------------------------
# get_resource_status
# ---------------------------------------------------------------------------


class TestGetResourceStatus:
    """Tests for the public get_resource_status() function."""

    @patch("core.resource_guard._query_vram", return_value=None)
    @patch("core.resource_guard.psutil.virtual_memory")
    def test_returns_snapshot_ram_only(self, mock_vmem, mock_vram):
        VmemResult = namedtuple("svmem", ["total", "used", "available", "percent"])
        mock_vmem.return_value = VmemResult(
            total=32 * 1024**3,  # 32 GB in bytes
            used=16 * 1024**3,
            available=16 * 1024**3,
            percent=50.0,
        )
        snap = get_resource_status()
        assert isinstance(snap, ResourceSnapshot)
        assert abs(snap.ram_total_mb - 32768) < 1  # 32 GB in MB
        assert abs(snap.ram_available_mb - 16384) < 1
        assert snap.vram_total_mb is None
        assert snap.vram_used_mb is None

    @patch("core.resource_guard._query_vram")
    @patch("core.resource_guard.psutil.virtual_memory")
    def test_returns_snapshot_with_vram(self, mock_vmem, mock_vram):
        VmemResult = namedtuple("svmem", ["total", "used", "available", "percent"])
        mock_vmem.return_value = VmemResult(
            total=32 * 1024**3,
            used=16 * 1024**3,
            available=16 * 1024**3,
            percent=50.0,
        )
        mock_vram.return_value = {"total": 16384.0, "used": 8000.0, "free": 8384.0}
        snap = get_resource_status()
        assert snap.vram_total_mb == 16384.0
        assert snap.vram_used_mb == 8000.0
        assert snap.vram_available_mb == 8384.0
        assert snap.vram_percent == round(8000.0 / 16384.0 * 100, 1)

    @patch("core.resource_guard._query_vram")
    @patch("core.resource_guard.psutil.virtual_memory")
    def test_vram_percent_zero_total(self, mock_vmem, mock_vram):
        """Edge case: vram total is 0 — should skip percent calculation."""
        VmemResult = namedtuple("svmem", ["total", "used", "available", "percent"])
        mock_vmem.return_value = VmemResult(
            total=32 * 1024**3,
            used=16 * 1024**3,
            available=16 * 1024**3,
            percent=50.0,
        )
        mock_vram.return_value = {"total": 0.0, "used": 0.0, "free": 0.0}
        snap = get_resource_status()
        assert snap.vram_total_mb == 0.0
        assert snap.vram_percent is None  # skipped because total == 0


# ---------------------------------------------------------------------------
# can_allocate
# ---------------------------------------------------------------------------


class TestCanAllocate:
    """Tests for the pre-flight allocation check."""

    @patch("core.resource_guard.get_resource_status")
    def test_returns_true_with_plenty_of_ram(self, mock_status):
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=10000,
            ram_available_mb=22000,
            ram_percent=31.25,
        )
        assert can_allocate(ram_mb=1000) is True

    @patch("core.resource_guard.get_resource_status")
    def test_returns_false_when_ram_insufficient(self, mock_status):
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=29000,
            ram_available_mb=3000,  # headroom = 3000 - 3072 = 0
            ram_percent=90.0,
        )
        assert can_allocate(ram_mb=100) is False

    @patch("core.resource_guard.get_resource_status")
    def test_returns_true_when_no_vram_requested(self, mock_status):
        """If no VRAM requested, VRAM is not checked."""
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=10000,
            ram_available_mb=22000,
            ram_percent=31.25,
        )
        assert can_allocate(ram_mb=0, vram_mb=0) is True

    @patch("core.resource_guard.get_resource_status")
    def test_vram_check_skipped_when_no_gpu(self, mock_status):
        """VRAM check is skipped when nvidia-smi is unavailable (vram_headroom is None)."""
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=10000,
            ram_available_mb=22000,
            ram_percent=31.25,
        )
        # Requesting VRAM but no GPU data — should still return True
        assert can_allocate(ram_mb=0, vram_mb=5000) is True

    @patch("core.resource_guard.get_resource_status")
    def test_returns_false_when_vram_insufficient(self, mock_status):
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=10000,
            ram_available_mb=22000,
            ram_percent=31.25,
            vram_total_mb=16000,
            vram_used_mb=14000,
            vram_available_mb=2000,  # headroom = 2000 - 2048 = 0
        )
        assert can_allocate(vram_mb=100) is False

    @patch("core.resource_guard.get_resource_status")
    def test_returns_true_when_vram_sufficient(self, mock_status):
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=10000,
            ram_available_mb=22000,
            ram_percent=31.25,
            vram_total_mb=16000,
            vram_used_mb=8000,
            vram_available_mb=8000,  # headroom = 8000 - 2048 = 5952
        )
        assert can_allocate(vram_mb=5000) is True

    @patch("core.resource_guard.get_resource_status")
    def test_zero_allocation_always_true(self, mock_status):
        """Requesting 0 MB should always pass."""
        mock_status.return_value = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=31000,
            ram_available_mb=1000,
            ram_percent=96.0,
        )
        assert can_allocate(ram_mb=0, vram_mb=0) is True


# ---------------------------------------------------------------------------
# ResourceGuard
# ---------------------------------------------------------------------------


class TestResourceGuard:
    """Tests for the background resource monitor."""

    def test_init_defaults(self):
        guard = ResourceGuard()
        assert guard.latest is None
        assert guard._task is None

    def test_init_custom_interval(self):
        guard = ResourceGuard(interval=5.0)
        assert guard._interval == 5.0

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        guard = ResourceGuard(interval=60.0)  # long interval so loop doesn't run
        with patch("core.resource_guard.get_resource_status") as mock_status:
            mock_status.return_value = ResourceSnapshot(
                ram_total_mb=32000,
                ram_used_mb=16000,
                ram_available_mb=16000,
                ram_percent=50.0,
            )
            await guard.start()
            assert guard._task is not None
            # Give the loop one tick to populate _latest
            await asyncio.sleep(0.1)
            await guard.stop()
            assert guard._task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Calling start() twice doesn't create a second task."""
        guard = ResourceGuard(interval=60.0)
        with patch("core.resource_guard.get_resource_status") as mock_status:
            mock_status.return_value = ResourceSnapshot(
                ram_total_mb=32000,
                ram_used_mb=16000,
                ram_available_mb=16000,
                ram_percent=50.0,
            )
            await guard.start()
            task1 = guard._task
            await guard.start()
            assert guard._task is task1  # same task
            await guard.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Stopping a guard that was never started is a no-op."""
        guard = ResourceGuard()
        await guard.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_latest_populated_after_start(self):
        guard = ResourceGuard(interval=60.0)
        snap = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
        )
        with patch("core.resource_guard.get_resource_status", return_value=snap):
            await guard.start()
            await asyncio.sleep(0.1)
            assert guard.latest is not None
            assert guard.latest.ram_total_mb == 32000
            await guard.stop()

    @pytest.mark.asyncio
    async def test_loop_handles_exception(self):
        """If get_resource_status raises, the loop continues."""
        call_count = 0

        def flaky_status():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("oops")
            return ResourceSnapshot(
                ram_total_mb=32000,
                ram_used_mb=16000,
                ram_available_mb=16000,
                ram_percent=50.0,
            )

        guard = ResourceGuard(interval=0.05)
        with patch("core.resource_guard.get_resource_status", side_effect=flaky_status):
            await guard.start()
            await asyncio.sleep(0.2)
            await guard.stop()
        # Loop should have recovered and populated latest after the error
        assert guard.latest is not None

    def test_health_dict_no_snapshot(self):
        guard = ResourceGuard()
        result = guard.health_dict()
        assert result == {"status": "unknown", "detail": "no snapshot yet"}

    def test_health_dict_ok(self):
        guard = ResourceGuard()
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
        )
        result = guard.health_dict()
        assert result["status"] == "ok"
        assert result["ram_used_mb"] == 16000
        assert result["ram_available_mb"] == 16000
        assert result["ram_headroom_mb"] == round(16000 - RAM_BUFFER_MB)

    def test_health_dict_warning(self):
        """Warning when headroom < 1024 MB but > 0."""
        guard = ResourceGuard()
        # headroom = 3572 - 3072 = 500 (< 1024)
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=28428,
            ram_available_mb=3572,
            ram_percent=88.8,
        )
        result = guard.health_dict()
        assert result["status"] == "warning"

    def test_health_dict_critical(self):
        """Critical when headroom <= 0."""
        guard = ResourceGuard()
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=30000,
            ram_available_mb=2000,
            ram_percent=93.75,
        )
        result = guard.health_dict()
        assert result["status"] == "critical"

    def test_health_dict_with_vram(self):
        guard = ResourceGuard()
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
            vram_total_mb=16000,
            vram_used_mb=8000,
            vram_available_mb=8000,
            vram_percent=50.0,
        )
        result = guard.health_dict()
        assert "vram_status" in result
        assert result["vram_status"] == "ok"
        assert result["vram_used_mb"] == 8000
        assert result["vram_available_mb"] == 8000

    def test_health_dict_vram_critical(self):
        guard = ResourceGuard()
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
            vram_total_mb=16000,
            vram_used_mb=15000,
            vram_available_mb=1000,
            vram_percent=93.75,
        )
        result = guard.health_dict()
        assert result["vram_status"] == "critical"

    def test_health_dict_vram_warning(self):
        guard = ResourceGuard()
        guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
            vram_total_mb=16000,
            vram_used_mb=13600,
            vram_available_mb=2400,  # headroom = 2400 - 2048 = 352 (< 512)
            vram_percent=85.0,
        )
        result = guard.health_dict()
        assert result["vram_status"] == "warning"


# ---------------------------------------------------------------------------
# Integration: ResourceGuard wired into MegaBotOrchestrator
# ---------------------------------------------------------------------------


class TestResourceGuardIntegration:
    """Tests that ResourceGuard is properly wired into the orchestrator."""

    def test_orchestrator_has_resource_guard(self, orchestrator):
        """Orchestrator.__init__ creates a ResourceGuard instance."""
        assert hasattr(orchestrator, "resource_guard")
        assert isinstance(orchestrator.resource_guard, ResourceGuard)

    @pytest.mark.asyncio
    async def test_lifecycle_start_calls_guard_start(self, orchestrator):
        """lifecycle.start() should call resource_guard.start()."""
        from core import lifecycle

        # Patch everything that start() calls so we don't actually connect
        with (
            patch.object(orchestrator.discovery, "scan"),
            patch.object(orchestrator.adapters["messaging"], "start", new_callable=AsyncMock),
            patch.object(orchestrator.adapters["gateway"], "start", new_callable=AsyncMock),
            patch.object(orchestrator.adapters["openclaw"], "connect", side_effect=Exception("skip")),
            patch.object(orchestrator.adapters["mcp"], "start_all", side_effect=Exception("skip")),
            patch.object(orchestrator.rag, "build_index", side_effect=Exception("skip")),
            patch.object(orchestrator.background_tasks, "start_all_tasks", new_callable=AsyncMock),
            patch.object(orchestrator.resource_guard, "start", new_callable=AsyncMock) as mock_guard_start,
            patch("asyncio.create_task", side_effect=Exception("skip health")),
        ):
            await lifecycle.start(orchestrator)
            mock_guard_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifecycle_shutdown_calls_guard_stop(self, orchestrator):
        """lifecycle.shutdown() should call resource_guard.stop()."""
        from core import lifecycle

        # Patch guard.stop to verify it gets called
        with patch.object(
            orchestrator.resource_guard,
            "stop",
            new_callable=AsyncMock,
        ) as mock_guard_stop:
            # Patch other shutdown steps to avoid side effects
            orchestrator.clients = set()
            orchestrator._health_task = None
            orchestrator.background_tasks._tasks = []
            orchestrator.health_monitor._tasks = []
            await lifecycle.shutdown(orchestrator)
            mock_guard_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_system_health_includes_resources(self, orchestrator):
        """get_system_health() should include 'resources' key from guard."""
        # Give the guard a fake snapshot so health_dict returns real data
        orchestrator.resource_guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=16000,
            ram_available_mb=16000,
            ram_percent=50.0,
        )

        health = await orchestrator.get_system_health()
        assert "resources" in health
        assert health["resources"]["status"] == "ok"
        assert "ram_used_mb" in health["resources"]
        assert "ram_available_mb" in health["resources"]

    @pytest.mark.asyncio
    async def test_get_system_health_resources_unknown_when_no_snapshot(self, orchestrator):
        """If guard has never run, resources status should be 'unknown'."""
        orchestrator.resource_guard._latest = None

        health = await orchestrator.get_system_health()
        assert "resources" in health
        assert health["resources"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_system_health_resources_critical(self, orchestrator):
        """Resources should report critical when RAM headroom is 0."""
        orchestrator.resource_guard._latest = ResourceSnapshot(
            ram_total_mb=32000,
            ram_used_mb=30000,
            ram_available_mb=2000,  # headroom = 2000 - 3072 = 0
            ram_percent=93.75,
        )

        health = await orchestrator.get_system_health()
        assert health["resources"]["status"] == "critical"

    @pytest.mark.asyncio
    async def test_get_system_health_handles_guard_error(self, orchestrator):
        """If resource_guard.health_dict() raises, health still returns."""
        with patch.object(
            orchestrator.resource_guard,
            "health_dict",
            side_effect=RuntimeError("boom"),
        ):
            health = await orchestrator.get_system_health()
            assert health["resources"]["status"] == "error"
            assert "boom" in health["resources"]["error"]
