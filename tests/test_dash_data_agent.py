"""Tests for features/dash_data/agent.py — DashDataAgent.

Covers: load_data, get_summary, analyze, execute_python_analysis.
Target: raise coverage from 19% to ~95%+.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from features.dash_data.agent import DashDataAgent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    llm = AsyncMock(spec=[])
    llm.generate = AsyncMock(return_value="LLM analysis result")
    return llm


@pytest.fixture
def agent(mock_llm):
    return DashDataAgent(llm=mock_llm)


@pytest.fixture
def agent_with_orchestrator(mock_llm):
    orch = MagicMock()
    orch.permissions = MagicMock()
    orch.admin_handler = MagicMock()
    orch.admin_handler.approval_queue = []
    orch.adapters = {"messaging": AsyncMock()}
    orch._to_platform_message = MagicMock(return_value="platform_msg")
    return DashDataAgent(llm=mock_llm, orchestrator=orch)


# ---------------------------------------------------------------------------
# load_data
# ---------------------------------------------------------------------------


class TestLoadData:
    @pytest.mark.asyncio
    async def test_load_csv(self, agent, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")

        result = await agent.load_data("test_ds", str(csv_file))

        assert "Successfully loaded dataset 'test_ds'" in result
        assert "2 records" in result
        assert "test_ds" in agent.datasets
        assert len(agent.datasets["test_ds"]) == 2

    @pytest.mark.asyncio
    async def test_load_json_list(self, agent, tmp_path):
        json_file = tmp_path / "data.json"
        json_file.write_text(json.dumps([{"x": 1}, {"x": 2}, {"x": 3}]))

        result = await agent.load_data("jds", str(json_file))

        assert "Successfully loaded dataset 'jds'" in result
        assert "3 records" in result

    @pytest.mark.asyncio
    async def test_load_json_dict(self, agent, tmp_path):
        """A JSON file containing a dict (not a list) should report 1 record."""
        json_file = tmp_path / "single.json"
        json_file.write_text(json.dumps({"key": "value"}))

        result = await agent.load_data("single", str(json_file))

        assert "1 records" in result

    @pytest.mark.asyncio
    async def test_load_unsupported_format(self, agent, tmp_path):
        xml_file = tmp_path / "data.xml"
        xml_file.write_text("<root/>")

        result = await agent.load_data("bad", str(xml_file))

        assert "Unsupported file format" in result
        assert "bad" not in agent.datasets

    @pytest.mark.asyncio
    async def test_load_file_not_found(self, agent):
        result = await agent.load_data("missing", "/nonexistent/path/data.csv")

        assert "Error loading data" in result


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_dataset_not_found(self, agent):
        result = await agent.get_summary("nope")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_empty_dataset(self, agent):
        agent.datasets["empty"] = []
        result = await agent.get_summary("empty")
        assert "empty or not a list" in result

    @pytest.mark.asyncio
    async def test_non_list_dataset(self, agent):
        agent.datasets["dict_ds"] = {"key": "value"}
        result = await agent.get_summary("dict_ds")
        assert "empty or not a list" in result

    @pytest.mark.asyncio
    async def test_valid_dataset_with_numerical_columns(self, agent):
        agent.datasets["nums"] = [
            {"name": "Alice", "score": "90", "grade": "A"},
            {"name": "Bob", "score": "80", "grade": "B"},
            {"name": "Carol", "score": "70", "grade": "C"},
        ]

        result = await agent.get_summary("nums")
        parsed = json.loads(result)

        assert parsed["name"] == "nums"
        assert parsed["total_records"] == 3
        assert "score" in parsed["numerical_stats"]
        stats = parsed["numerical_stats"]["score"]
        assert stats["min"] == 70.0
        assert stats["max"] == 90.0
        assert stats["avg"] == 80.0
        assert stats["count"] == 3
        assert len(parsed["sample"]) == 2

    @pytest.mark.asyncio
    async def test_non_numeric_columns_skipped(self, agent):
        """Columns with purely non-numeric data should not appear in stats."""
        agent.datasets["text"] = [
            {"label": "hello", "value": "5"},
            {"label": "world", "value": "not_a_number"},
        ]

        result = await agent.get_summary("text")
        parsed = json.loads(result)

        # 'label' has no numeric values
        assert "label" not in parsed["numerical_stats"]
        # 'value' has one numeric entry ("5"), "not_a_number" is skipped
        assert "value" in parsed["numerical_stats"]
        assert parsed["numerical_stats"]["value"]["count"] == 1


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_dataset_not_found(self, agent):
        result = await agent.analyze("nope", "what's the trend?")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_with_reason_method(self, mock_llm):
        """When llm has a reason() method, analyze should use it."""
        mock_llm.reason = AsyncMock(return_value="Deep reasoning result")
        agent = DashDataAgent(llm=mock_llm)
        agent.datasets["ds"] = [{"a": "1"}]

        result = await agent.analyze("ds", "explain trends")

        assert result == "Deep reasoning result"
        mock_llm.reason.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_to_generate(self, agent):
        """Without reason(), analyze falls back to generate()."""
        agent.datasets["ds"] = [{"a": "1"}]

        result = await agent.analyze("ds", "explain trends")

        assert result == "LLM analysis result"
        agent.llm.generate.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_python_analysis
# ---------------------------------------------------------------------------


class TestExecutePythonAnalysis:
    @pytest.mark.asyncio
    async def test_dataset_not_found(self, agent):
        result = await agent.execute_python_analysis("nope", "pass")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_permission_denied(self, agent_with_orchestrator):
        """When is_authorized returns False, execution is denied."""
        agent_with_orchestrator.orchestrator.permissions.is_authorized.return_value = False
        agent_with_orchestrator.datasets["ds"] = [{"a": 1}]

        result = await agent_with_orchestrator.execute_python_analysis("ds", "pass")

        assert "Permission denied" in result

    @pytest.mark.asyncio
    async def test_permission_ask_queued(self, agent_with_orchestrator):
        """When is_authorized returns 'ask', the action is queued for approval."""
        agent_with_orchestrator.orchestrator.permissions.is_authorized.return_value = "ask"
        agent_with_orchestrator.orchestrator.approval_queue = []
        agent_with_orchestrator.datasets["ds"] = [{"a": 1}]

        result = await agent_with_orchestrator.execute_python_analysis("ds", "result = 42")

        assert "queued for approval" in result
        assert len(agent_with_orchestrator.orchestrator.admin_handler.approval_queue) == 1

    @pytest.mark.asyncio
    async def test_permission_none_queued(self, agent_with_orchestrator):
        """When is_authorized returns None, the action is queued for approval."""
        agent_with_orchestrator.orchestrator.permissions.is_authorized.return_value = None
        agent_with_orchestrator.orchestrator.approval_queue = []
        agent_with_orchestrator.datasets["ds"] = [{"a": 1}]

        result = await agent_with_orchestrator.execute_python_analysis("ds", "result = 42")

        assert "queued for approval" in result

    @pytest.mark.asyncio
    async def test_no_orchestrator_direct_exec(self, agent):
        """Without an orchestrator, code executes directly."""
        agent.datasets["ds"] = [{"a": 1}]

        result = await agent.execute_python_analysis("ds", "result = len(data)")

        assert result == "1"

    @pytest.mark.asyncio
    async def test_successful_exec_with_result(self, agent):
        """Code that sets 'result' returns that value."""
        agent.datasets["ds"] = [{"val": 10}, {"val": 20}]

        result = await agent.execute_python_analysis("ds", "result = sum(int(r['val']) for r in data)")

        assert result == "30"

    @pytest.mark.asyncio
    async def test_no_result_variable(self, agent):
        """Code that doesn't set 'result' returns the stringified default (None)."""
        agent.datasets["ds"] = [{"a": 1}]

        result = await agent.execute_python_analysis("ds", "x = 42")

        # local_vars starts with result=None; exec doesn't set it, so
        # str(None) == "None" is returned
        assert result == "None"

    @pytest.mark.asyncio
    async def test_execution_error(self, agent):
        """Code that raises an exception returns an error message."""
        agent.datasets["ds"] = [{"a": 1}]

        # Use a plain raise with a string expression (ValueError was removed
        # from safe builtins to prevent __traceback__ frame escape attacks).
        result = await agent.execute_python_analysis("ds", "x = 1 / 0")

        assert "Python execution error" in result
        assert "division by zero" in result


# ---------------------------------------------------------------------------
# Blocked pattern detection (from test_coverage_phase4.py)
# ---------------------------------------------------------------------------


class TestDashDataBlockedPatterns:
    """Cover features/dash_data/agent.py line 230."""

    @pytest.fixture
    def agent(self):
        llm = AsyncMock(spec=[])
        llm.generate = AsyncMock(return_value="result")
        a = DashDataAgent(llm=llm)
        # Pre-load a dataset so execute_python_analysis doesn't bail early
        a.datasets["test_ds"] = [{"x": 1}, {"x": 2}]
        return a

    @pytest.mark.asyncio
    async def test_blocked_import_os(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import os\nos.listdir()")
        assert "Blocked pattern" in res
        assert "import" in res.lower()

    @pytest.mark.asyncio
    async def test_blocked_eval(self, agent):
        res = await agent.execute_python_analysis("test_ds", "eval('1+1')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_exec(self, agent):
        res = await agent.execute_python_analysis("test_ds", "exec('x=1')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_subprocess(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import subprocess\nsubprocess.run(['ls'])")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_open(self, agent):
        res = await agent.execute_python_analysis("test_ds", "f = open('/etc/passwd')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_getattr(self, agent):
        res = await agent.execute_python_analysis("test_ds", "getattr(data, '__class__')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_compile(self, agent):
        res = await agent.execute_python_analysis("test_ds", "compile('1+1', '<str>', 'eval')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_dunder_import(self, agent):
        res = await agent.execute_python_analysis("test_ds", "__import__('os')")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_importlib(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import importlib")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_sys_dot(self, agent):
        res = await agent.execute_python_analysis("test_ds", "import sys\nsys.exit()")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_subclasses(self, agent):
        res = await agent.execute_python_analysis("test_ds", "''.__class__.__subclasses__()")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_globals_dunder(self, agent):
        res = await agent.execute_python_analysis("test_ds", "print(__globals__)")
        assert "Blocked pattern" in res

    @pytest.mark.asyncio
    async def test_blocked_builtins_dunder(self, agent):
        res = await agent.execute_python_analysis("test_ds", "print(__builtins__)")
        assert "Blocked pattern" in res


# ==============================================================
# Round 3 — merged from test_coverage_round3.py
# ==============================================================


@pytest.mark.asyncio
async def test_dash_data_stats_value_error():
    """Lines 71-72: ValueError/TypeError in numeric conversion -> continue."""
    agent = DashDataAgent.__new__(DashDataAgent)
    agent.datasets = {}

    agent.datasets["test"] = [
        {"col_a": "123", "col_b": "hello"},
        {"col_a": "456", "col_b": "world"},
    ]

    original_float = float

    def patched_float(val):
        if val in ("123", "456"):
            raise ValueError("forced error for test")
        return original_float(val)

    with patch("builtins.float", side_effect=patched_float):
        result = await agent.get_summary("test")

    import json

    parsed = json.loads(result)
    assert parsed["name"] == "test"
    assert parsed["total_records"] == 2
