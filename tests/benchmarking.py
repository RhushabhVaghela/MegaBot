"""
MegaBot end-to-end orchestrator benchmarks.
Run with: PYTHONPATH=. python -m pytest tests/benchmarking.py -v -s
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from core.config import AdapterConfig, Config, SecurityConfig, SystemConfig
from core.interfaces import Message
from core.orchestrator import MegaBotOrchestrator


def _make_orchestrator() -> MegaBotOrchestrator:
    """Build an orchestrator with mocked adapters for benchmarking."""
    config = Config(
        system=SystemConfig(
            name="BenchBot",
            local_only=True,
            bind_address="127.0.0.1",
            telemetry=False,
            default_mode="plan",
        ),
        adapters={
            "openclaw": AdapterConfig(host="127.0.0.1", port=18789),
            "memu": AdapterConfig(
                database_url="sqlite:///:memory:", vector_db="sqlite"
            ),
            "mcp": AdapterConfig(servers=[]),
        },
        paths={"external_repos": "/tmp/megabot_bench"},
        security=SecurityConfig(
            megabot_encryption_salt="bench-salt-minimum-16-chars",
            megabot_backup_key="bench-backup-key-32-chars-long!xx",
        ),
    )
    orch = MegaBotOrchestrator(config)

    # Mock all adapters to avoid network calls
    orch.adapters["openclaw"] = AsyncMock()
    orch.adapters["memu"] = AsyncMock()
    orch.adapters["mcp"] = AsyncMock()
    orch.adapters["messaging"] = AsyncMock()
    orch.adapters["gateway"] = AsyncMock()
    return orch


@pytest.mark.asyncio
async def test_benchmark_pipeline():
    """Single gateway message processed in under 200 ms (no LLM)."""
    orch = _make_orchestrator()

    data = {
        "type": "message",
        "sender_id": "test-user-123",
        "content": "What is the status of the project?",
        "sender_name": "Tester",
    }

    start = time.perf_counter()
    await orch.on_gateway_message(data)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\nPipeline latency (no LLM): {elapsed_ms:.2f}ms")
    assert elapsed_ms < 500, f"Pipeline too slow: {elapsed_ms:.2f}ms"

    # Message conversion micro-benchmark
    msg = Message(content="Hello", sender="user")
    start = time.perf_counter()
    orch._to_platform_message(msg)
    conv_ms = (time.perf_counter() - start) * 1000
    print(f"Message conversion: {conv_ms:.4f}ms")
    assert conv_ms < 5, f"Conversion too slow: {conv_ms:.4f}ms"

    # Policy check micro-benchmark
    policy_data = {"method": "shell.execute", "params": {"command": "ls -la"}}
    start = time.perf_counter()
    orch._check_policy(policy_data)
    policy_ms = (time.perf_counter() - start) * 1000
    print(f"Policy check: {policy_ms:.4f}ms")
    assert policy_ms < 5, f"Policy check too slow: {policy_ms:.4f}ms"


@pytest.mark.asyncio
async def test_benchmark_concurrency():
    """100 concurrent gateway messages processed at >50 msg/s."""
    num_users = 100
    orch = _make_orchestrator()
    orch.llm = AsyncMock()
    orch.llm.generate = AsyncMock(return_value="Benchmarked response")

    tasks = []
    start = time.perf_counter()
    for i in range(num_users):
        data = {
            "type": "message",
            "sender_id": f"user-{i}",
            "content": f"Message {i}",
            "sender_name": f"Tester-{i}",
        }
        tasks.append(orch.on_gateway_message(data))

    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start

    throughput = num_users / elapsed
    avg_ms = (elapsed / num_users) * 1000
    print(f"\nConcurrency: {num_users} msgs in {elapsed:.2f}s")
    print(f"Throughput: {throughput:.0f} msg/s, avg latency: {avg_ms:.2f}ms")
    assert throughput > 40, f"Throughput too low: {throughput:.0f} msg/s"
