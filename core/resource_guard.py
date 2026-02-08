"""Resource guard — monitors RAM and VRAM to prevent out-of-memory crashes.

Provides:
- ``get_resource_status()`` — snapshot of current RAM/VRAM usage
- ``can_allocate(ram_mb, vram_mb)`` — pre-flight check before heavy operations
- ``ResourceGuard`` — singleton that runs periodic checks and can trigger eviction
- ``LRUCache`` — bounded dict with automatic eviction on size limit

Design decisions:
- **3 GB RAM buffer**: ensures the OS and other processes have headroom.
- **2 GB VRAM buffer**: ensures the GPU driver and display have headroom.
- Buffers are hardcoded (not configurable) because they represent safety
  minimums — lowering them risks system instability on WSL2 with 32 GB RAM.
- VRAM monitoring is best-effort: if ``nvidia-smi`` is unavailable, VRAM
  checks are skipped and ``can_allocate`` always returns True for VRAM.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TypeVar, Generic

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAM_BUFFER_MB: int = 3 * 1024  # 3 GB reserved for OS / other processes
VRAM_BUFFER_MB: int = 2 * 1024  # 2 GB reserved for GPU driver / display
_CHECK_INTERVAL_SECONDS: float = 30.0  # How often the background loop runs

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ResourceSnapshot:
    """Point-in-time resource usage snapshot."""

    ram_total_mb: float
    ram_used_mb: float
    ram_available_mb: float
    ram_percent: float
    vram_total_mb: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_available_mb: Optional[float] = None
    vram_percent: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def ram_headroom_mb(self) -> float:
        """How much RAM can be allocated before hitting the buffer."""
        return max(0.0, self.ram_available_mb - RAM_BUFFER_MB)

    @property
    def vram_headroom_mb(self) -> Optional[float]:
        """How much VRAM can be allocated before hitting the buffer."""
        if self.vram_available_mb is None:
            return None
        return max(0.0, self.vram_available_mb - VRAM_BUFFER_MB)


# ---------------------------------------------------------------------------
# VRAM helper (nvidia-smi)
# ---------------------------------------------------------------------------


def _query_vram() -> Optional[Dict[str, float]]:
    """Query VRAM via ``nvidia-smi``.  Returns None if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used,memory.free",
                "--format=csv,nounits,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Take the first GPU line
        line = result.stdout.strip().splitlines()[0]
        total, used, free = (float(v.strip()) for v in line.split(","))
        return {"total": total, "used": used, "free": free}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_resource_status() -> ResourceSnapshot:
    """Return a snapshot of current system resource usage."""
    mem = psutil.virtual_memory()
    snap = ResourceSnapshot(
        ram_total_mb=mem.total / (1024 * 1024),
        ram_used_mb=mem.used / (1024 * 1024),
        ram_available_mb=mem.available / (1024 * 1024),
        ram_percent=mem.percent,
    )

    vram = _query_vram()
    if vram is not None:
        snap.vram_total_mb = vram["total"]
        snap.vram_used_mb = vram["used"]
        snap.vram_available_mb = vram["free"]
        if vram["total"] > 0:
            snap.vram_percent = round(vram["used"] / vram["total"] * 100, 1)

    return snap


def can_allocate(ram_mb: float = 0, vram_mb: float = 0) -> bool:
    """Pre-flight check: can we allocate *ram_mb* and *vram_mb* without
    breaching the safety buffers?

    Returns True if the allocation is safe, False otherwise.
    VRAM checks are skipped if ``nvidia-smi`` is unavailable.
    """
    snap = get_resource_status()

    if ram_mb > 0 and snap.ram_headroom_mb < ram_mb:
        logger.warning(
            "RAM allocation denied: requested %.0f MB but only %.0f MB headroom (buffer=%d MB)",
            ram_mb,
            snap.ram_headroom_mb,
            RAM_BUFFER_MB,
        )
        return False

    if vram_mb > 0 and snap.vram_headroom_mb is not None:
        if snap.vram_headroom_mb < vram_mb:
            logger.warning(
                "VRAM allocation denied: requested %.0f MB but only %.0f MB headroom (buffer=%d MB)",
                vram_mb,
                snap.vram_headroom_mb,
                VRAM_BUFFER_MB,
            )
            return False

    return True


# ---------------------------------------------------------------------------
# LRU Cache (bounded dict with eviction)
# ---------------------------------------------------------------------------

KT = TypeVar("KT")
VT = TypeVar("VT")


class LRUCache(Generic[KT, VT]):
    """Bounded dict with LRU eviction.

    Drop-in replacement for unbounded dicts used as caches throughout the
    codebase.  When ``maxsize`` is reached, the least-recently-used entry is
    evicted on the next ``set`` / ``__setitem__``.

    Thread-safety: **not** thread-safe.  All callers in MegaBot run on the
    same asyncio event loop so this is fine.
    """

    def __init__(self, maxsize: int = 1024):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._data: OrderedDict[KT, VT] = OrderedDict()

    # -- dict-like interface --

    def __setitem__(self, key: KT, value: VT) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
        else:
            if len(self._data) >= self._maxsize:
                self._data.popitem(last=False)  # evict oldest
            self._data[key] = value

    def __getitem__(self, key: KT) -> VT:
        self._data.move_to_end(key)
        return self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __delitem__(self, key: KT) -> None:
        del self._data[key]

    def get(self, key: KT, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key: KT, *args: Any) -> Any:
        return self._data.pop(key, *args)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def clear(self) -> None:
        self._data.clear()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def __repr__(self) -> str:
        return f"LRUCache(maxsize={self._maxsize}, size={len(self._data)})"


# ---------------------------------------------------------------------------
# ResourceGuard — background monitor
# ---------------------------------------------------------------------------


class ResourceGuard:
    """Singleton-style resource monitor that runs a background check loop.

    Usage::

        guard = ResourceGuard()
        await guard.start()  # spawns background task
        ...
        await guard.stop()

    The guard periodically snapshots resource usage and logs warnings when
    headroom drops below the safety buffers.
    """

    def __init__(self, *, interval: float = _CHECK_INTERVAL_SECONDS):
        self._interval = interval
        self._task: Optional[asyncio.Task] = None
        self._latest: Optional[ResourceSnapshot] = None
        self._warning_issued_ram = False
        self._warning_issued_vram = False

    @property
    def latest(self) -> Optional[ResourceSnapshot]:
        """Most recent snapshot (None if ``start()`` hasn't been called)."""
        return self._latest

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._loop())
        logger.info("ResourceGuard started (interval=%.0fs)", self._interval)

    async def stop(self) -> None:
        """Stop the background monitoring loop."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.debug("ResourceGuard task cancelled during stop")
        except Exception as e:
            logger.debug("ResourceGuard task raised during stop: %s", e)
        self._task = None
        logger.info("ResourceGuard stopped")

    async def _loop(self) -> None:
        """Periodically check resources and log warnings."""
        while True:
            try:
                snap = await asyncio.get_running_loop().run_in_executor(None, get_resource_status)
                self._latest = snap

                # RAM warning
                if snap.ram_headroom_mb <= 0:
                    if not self._warning_issued_ram:
                        logger.critical(
                            "RAM CRITICAL: %.0f MB available, buffer is %d MB. System may become unstable.",
                            snap.ram_available_mb,
                            RAM_BUFFER_MB,
                        )
                        self._warning_issued_ram = True
                else:
                    self._warning_issued_ram = False

                # VRAM warning
                if snap.vram_headroom_mb is not None and snap.vram_headroom_mb <= 0:
                    if not self._warning_issued_vram:
                        logger.critical(
                            "VRAM CRITICAL: %.0f MB available, buffer is %d MB. GPU operations may fail.",
                            snap.vram_available_mb,
                            VRAM_BUFFER_MB,
                        )
                        self._warning_issued_vram = True
                else:
                    self._warning_issued_vram = False

            except Exception as e:
                logger.error("ResourceGuard check failed: %s", e)

            await asyncio.sleep(self._interval)

    def health_dict(self) -> Dict[str, Any]:
        """Return a dict suitable for inclusion in system health responses."""
        snap = self._latest
        if snap is None:
            return {"status": "unknown", "detail": "no snapshot yet"}

        status = "ok"
        if snap.ram_headroom_mb <= 0:
            status = "critical"
        elif snap.ram_headroom_mb < 1024:  # less than 1 GB headroom
            status = "warning"

        result: Dict[str, Any] = {
            "status": status,
            "ram_used_mb": round(snap.ram_used_mb),
            "ram_available_mb": round(snap.ram_available_mb),
            "ram_headroom_mb": round(snap.ram_headroom_mb),
            "ram_percent": snap.ram_percent,
        }

        if snap.vram_total_mb is not None:
            vram_status = "ok"
            if snap.vram_headroom_mb is not None and snap.vram_headroom_mb <= 0:
                vram_status = "critical"
            elif snap.vram_headroom_mb is not None and snap.vram_headroom_mb < 512:
                vram_status = "warning"
            result["vram_status"] = vram_status
            result["vram_used_mb"] = round(snap.vram_used_mb or 0)
            result["vram_available_mb"] = round(snap.vram_available_mb or 0)
            result["vram_headroom_mb"] = round(snap.vram_headroom_mb or 0)
            result["vram_percent"] = snap.vram_percent

        return result
