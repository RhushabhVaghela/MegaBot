"""
MegaBot core component benchmarks.
Run with: PYTHONPATH=. python -m pytest tests/benchmarks.py -v -s
"""

import json
import time

import pytest

from adapters.memu_adapter import MemUAdapter
from adapters.messaging import (
    MegaBotMessagingServer,
    PlatformMessage,
    SecureWebSocket,
)


@pytest.mark.asyncio
async def test_benchmark_encryption():
    """1 000 encrypt/decrypt cycles of a 1 KB message under 2 s."""
    secure_ws = SecureWebSocket(password="benchmark-secret")
    message = "A" * 1024  # 1 KB
    iterations = 1_000

    start = time.perf_counter()
    for _ in range(iterations):
        enc = secure_ws.encrypt(message)
        secure_ws.decrypt(enc)
    elapsed = time.perf_counter() - start

    throughput = iterations / elapsed
    avg_ms = (elapsed / iterations) * 1000
    print(f"\nEncryption: {throughput:,.0f} ops/s, avg {avg_ms:.4f}ms")
    assert elapsed < 2.0, f"Encryption benchmark too slow: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_benchmark_memory_store(tmp_path):
    """100 store() calls under 2 s."""
    db_path = str(tmp_path / "benchmark.db")
    adapter = MemUAdapter(memu_path="/tmp", db_url=f"sqlite:///{db_path}")
    iterations = 100

    start = time.perf_counter()
    for i in range(iterations):
        await adapter.store(f"key_{i}", f"content_{i}")
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / iterations) * 1000
    print(f"\nMemory store: {iterations} writes in {elapsed:.4f}s, avg {avg_ms:.4f}ms")
    assert elapsed < 2.0, f"Memory store benchmark too slow: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_benchmark_messaging_throughput():
    """500 serialize+encrypt+decrypt cycles under 2 s."""
    server = MegaBotMessagingServer(enable_encryption=True)
    msg = PlatformMessage(
        id="bench-1",
        platform="native",
        sender_id="user-1",
        sender_name="Benchmarking",
        chat_id="chat-1",
        content="Hello world",
    )
    iterations = 500

    start = time.perf_counter()
    for _ in range(iterations):
        data = json.dumps(msg.to_dict())
        if server.secure_ws:
            enc = server.secure_ws.encrypt(data)
            dec = server.secure_ws.decrypt(enc)
            json.loads(dec)
        else:
            json.loads(data)
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / iterations) * 1000
    print(f"\nMessaging throughput: {iterations} ops in {elapsed:.4f}s, avg {avg_ms:.4f}ms")
    assert elapsed < 2.0, f"Messaging throughput too slow: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_benchmark_layer_fetching(tmp_path):
    """Layered fetch of 1 000 stored items in 10 batches under 5 s."""
    db_path = str(tmp_path / "bench_layer.db")
    adapter = MemUAdapter(memu_path="/tmp", db_url=f"sqlite:///{db_path}")

    # Fill with data
    for i in range(1_000):
        await adapter.store(f"item_{i}", "A" * 100)

    batch_size = 100
    total_fetched = 0

    start = time.perf_counter()
    for _offset in range(0, 1_000, batch_size):
        results = await adapter.search("item_")
        total_fetched += len(results[:batch_size])
    elapsed = time.perf_counter() - start

    num_layers = 1_000 / batch_size
    layer_ms = (elapsed / num_layers) * 1000
    print(f"\nLayer fetching: {num_layers:.0f} batches in {elapsed:.4f}s, avg {layer_ms:.4f}ms/batch")
    assert elapsed < 5.0, f"Layer fetching too slow: {elapsed:.2f}s"
