"""Tests for SubAgent module"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from core.agents import SubAgent


@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock()
    orchestrator.llm = AsyncMock()
    orchestrator._execute_tool_for_sub_agent = AsyncMock(return_value="Tool result")
    return orchestrator


class TestSubAgent:
    """Test suite for SubAgent class"""

    @pytest.mark.asyncio
    async def test_generate_plan(self, mock_orchestrator):
        """Test plan generation from LLM response"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Fix bugs", mock_orchestrator)

        # Mock LLM response with a numbered list
        mock_orchestrator.llm.generate.return_value = "1. Read file\n2. Fix bug\n3. Run tests"

        plan = await sub_agent.generate_plan()

        assert len(plan) == 3
        assert plan[0] == "1. Read file"
        assert plan[1] == "2. Fix bug"
        assert plan[2] == "3. Run tests"

    @pytest.mark.asyncio
    async def test_run_text_response(self, mock_orchestrator):
        """Test sub-agent run loop with text response"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Say hello", mock_orchestrator)
        sub_agent.plan = ["Step 1"]

        mock_orchestrator.llm.generate.return_value = "Hello world"

        result = await sub_agent.run()

        assert result == "Hello world"
        assert len(sub_agent.history) == 1

    @pytest.mark.asyncio
    async def test_run_tool_use(self, mock_orchestrator):
        """Test sub-agent run loop with tool use delegation"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Read a file", mock_orchestrator)
        sub_agent.plan = ["Step 1"]

        # Mock sequence of responses: 1. Tool use, 2. Text result
        mock_orchestrator.llm.generate.side_effect = [
            [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "read_file",
                    "input": {"path": "test.txt"},
                }
            ],
            "File content: hello",
        ]

        result = await sub_agent.run()

        assert result == "File content: hello"
        assert mock_orchestrator._execute_tool_for_sub_agent.called

    @pytest.mark.asyncio
    async def test_run_max_steps(self, mock_orchestrator):
        """Test sub-agent reaching max steps"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Never ending task", mock_orchestrator)
        sub_agent.plan = ["Step 1"]
        sub_agent.max_steps = 2

        # Always return a tool use to keep the loop going
        mock_orchestrator.llm.generate.return_value = [
            {
                "type": "tool_use",
                "id": "call-x",
                "name": "read_file",
                "input": {"path": "test.txt"},
            }
        ]

        result = await sub_agent.run()

        assert "reached max steps" in result

    @pytest.mark.asyncio
    async def test_run_exception(self, mock_orchestrator):
        """Test error handling in run loop"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Error task", mock_orchestrator)
        sub_agent.plan = ["Step 1"]

        mock_orchestrator.llm.generate.side_effect = RuntimeError("LLM error")

        result = await sub_agent.run()

        assert "Sub-agent error: LLM error" in result

    def test_get_sub_tools_senior_dev(self, mock_orchestrator):
        """Test tool filtering for Senior Dev role"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "task", mock_orchestrator)
        tools = sub_agent._get_sub_tools()

        tool_names = [t["name"] for t in tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "run_test" in tool_names
        assert "query_rag" in tool_names
        assert "analyze_data" not in tool_names

    def test_get_sub_tools_data_scientist(self, mock_orchestrator):
        """Test tool filtering for Data Scientist role"""
        sub_agent = SubAgent("TestBot", "Data Scientist", "task", mock_orchestrator)
        tools = sub_agent._get_sub_tools()

        tool_names = [t["name"] for t in tools]
        assert "analyze_data" in tool_names
        assert "read_file" in tool_names
        assert "write_file" not in tool_names

    def test_role_fallback(self, mock_orchestrator):
        """Test fallback for unknown roles"""
        sub_agent = SubAgent("TestBot", "Wizard", "task", mock_orchestrator)
        assert sub_agent.role == "Assistant"

        tools = sub_agent._get_sub_tools()
        tool_names = [t["name"] for t in tools]
        assert "query_rag" in tool_names
        assert "read_file" not in tool_names

    @pytest.mark.asyncio
    async def test_run_list_response_no_tool_calls(self, mock_orchestrator):
        """Test sub-agent run loop with list response but no tool calls (lines 77-80)"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Say hello", mock_orchestrator)
        sub_agent.plan = ["Step 1"]

        # Mock list response with only text blocks
        mock_orchestrator.llm.generate.return_value = [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "there!"},
        ]

        result = await sub_agent.run()

        assert result == "Hello there!"

    @pytest.mark.asyncio
    async def test_run_auto_generate_plan(self, mock_orchestrator):
        """Test sub-agent run loop with auto plan generation (line 50)"""
        sub_agent = SubAgent("TestBot", "Senior Dev", "Say hello", mock_orchestrator)
        # plan is empty here

        mock_orchestrator.llm.generate.side_effect = [
            "1. Step one",  # response for generate_plan
            "Hello world",  # response for run
        ]

        result = await sub_agent.run()

        assert result == "Hello world"
        assert sub_agent.plan == ["1. Step one"]
