import json

# Mock pyautogui before importing anything that uses it
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

mock_pyautogui = MagicMock()
sys.modules["pyautogui"] = mock_pyautogui
mock_mouseinfo = MagicMock()
sys.modules["mouseinfo"] = mock_mouseinfo

from core.interfaces import Message
from core.orchestrator import MegaBotOrchestrator


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.system.default_mode = "plan"
    config.system.name = "MegaBot"
    config.paths = {"external_repos": "/tmp", "workspaces": "/tmp"}

    # Mocking adapters dict
    openclaw_mock = MagicMock()
    openclaw_mock.host = "localhost"
    openclaw_mock.port = 1234

    memu_mock = MagicMock()
    memu_mock.database_url = "sqlite://"

    config.adapters = {
        "llm": {"provider": "anthropic"},
        "openclaw": openclaw_mock,
        "memu": memu_mock,
        "mcp": MagicMock(servers=[]),
    }

    config.admins = ["admin"]
    config.policies = {"allow": [], "deny": []}
    config.model_dump.return_value = {}
    return config


@pytest.fixture
def orchestrator(mock_config):
    with (
        patch("core.orchestrator.ModuleDiscovery"),
        patch("core.orchestrator.OpenClawAdapter"),
        patch("core.orchestrator.MemUAdapter"),
        patch("core.orchestrator.MCPManager"),
    ):
        orc = MegaBotOrchestrator(mock_config)
        orc.adapters["openclaw"] = AsyncMock()
        orc.adapters["memu"] = AsyncMock()
        orc.adapters["mcp"] = AsyncMock()
        orc.llm = AsyncMock()
        orc.memory = AsyncMock()
        return orc


@pytest.mark.asyncio
async def test_memory_learning_and_distillation(orchestrator):
    """
    Simulates a sub-agent task that records a lesson,
    and then verifies that a subsequent task retrieves and distills that lesson.
    """
    # 1. Simulate Sub-Agent Synthesis recording a lesson
    agent_name = "SecurityBot"
    task = "Audit file system"
    raw_result = "Found unauthorized access pattern in /etc/config"

    # Mock LLM response for:
    # 1. Pre-flight validation (VALID)
    # 2. Synthesis (JSON with lesson)
    # 3. Distillation (Top 3 points)
    # 4. Final LLM response for build (text)

    lesson_content = "CRITICAL: Never allow direct write access to /etc/config without Tirith validation."
    synthesis_json = json.dumps(
        {
            "summary": "Audit complete",
            "findings": ["Unauthorized access in /etc/config"],
            "learned_lesson": lesson_content,
            "next_steps": ["Patch /etc/config"],
        }
    )
    distilled_memory = "DISTILLED: 1. No direct write to /etc/config. 2. Use Tirith Guard."

    async def mock_gen(context=None, messages=None, **kwargs):
        ctx = str(context).lower()
        msg_content = messages[0]["content"] if messages else ""
        if "pre-flight" in ctx or "validate" in msg_content.lower():
            return "VALID"
        if "synthesis" in ctx or "integrate" in msg_content.lower():
            return synthesis_json
        if "keyword" in ctx:
            return "python, config"
        if "distillation" in ctx:
            return distilled_memory
        return "I will check the config."

    orchestrator.llm.generate.side_effect = mock_gen

    # Trigger _spawn_sub_agent (we mock the SubAgent class inside)
    with patch("core.agent_coordinator.SubAgent") as MockSubAgent:
        mock_agent = MockSubAgent.return_value
        mock_agent.run = AsyncMock(return_value=raw_result)
        mock_agent.generate_plan = AsyncMock(return_value=["Step 1"])

        await orchestrator._spawn_sub_agent({"name": agent_name, "task": task, "role": "Senior Dev"})

        # Verify memory write
        orchestrator.memory.memory_write.assert_called_once()
        kwargs = orchestrator.memory.memory_write.call_args.kwargs
        assert kwargs["type"] == "learned_lesson"
        assert lesson_content in kwargs["content"]

    # 2. Simulate a new task that triggers distillation
    # Mock memory search return (4 lessons to trigger distillation > 3)
    orchestrator.memory.memory_search.return_value = [
        {"content": lesson_content, "type": "learned_lesson"},
        {"content": "Lesson 2", "type": "learned_lesson"},
        {"content": "Lesson 3", "type": "learned_lesson"},
        {"content": "Lesson 4", "type": "learned_lesson"},
    ]

    mock_ws = AsyncMock()
    msg = Message(content="Update /etc/config", sender="user")

    # Reset call count to check distillation specifically
    # orchestrator.llm.generate.side_effect still has 2 items left: distilled_memory and "I will check..."

    await orchestrator.run_autonomous_build(msg, mock_ws)

    # Verify the context of the build task contains the distilled memory
    # The last call to llm.generate should have the distilled memory in its context
    last_call = orchestrator.llm.generate.call_args_list[-1]
    context = last_call.kwargs.get("context", "")
    assert distilled_memory in context
    print("✅ Memory distillation successfully verified in LLM context.")
