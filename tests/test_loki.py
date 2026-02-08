"""
Tests for Loki Mode
"""

import subprocess

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core.loki import LokiMode


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator with required attributes"""
    orchestrator = MagicMock()
    orchestrator.last_active_chat = {"chat_id": "test_chat", "platform": "test"}
    orchestrator.memory = MagicMock()
    orchestrator.llm = AsyncMock()  # Make it async
    orchestrator.adapters = {"memu": AsyncMock()}  # Make it async
    return orchestrator


@pytest.fixture
def loki_mode(mock_orchestrator):
    return LokiMode(mock_orchestrator)


class TestLokiMode:
    """Test Loki Mode functionality"""

    @pytest.mark.asyncio
    async def test_init(self, mock_orchestrator):
        """Test LokiMode initialization"""
        loki = LokiMode(mock_orchestrator)
        assert loki.orchestrator == mock_orchestrator
        assert loki.is_active is False

    @pytest.mark.asyncio
    async def test_relay_status_no_active_chat(self, loki_mode):
        """Test _relay_status with no active chat"""
        loki_mode.orchestrator.last_active_chat = None
        await loki_mode._relay_status("test")
        # Should not call send_platform_message
        loki_mode.orchestrator.send_platform_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_relay_status_with_active_chat(self, loki_mode):
        """Test _relay_status with active chat"""
        with patch("core.loki.safe_create_task") as mock_task:
            await loki_mode._relay_status("test message")
            mock_task.assert_called_once()
            # Verify the task creation - the coroutine should call send_platform_message
            call_args = mock_task.call_args[0][0]
            # The coroutine is async, we can't easily inspect it, but we can check it was called
            # For now, just verify safe_create_task was called
            assert mock_task.called

    @pytest.mark.asyncio
    async def test_retrieve_learned_lessons_no_lessons(self, loki_mode):
        """Test _retrieve_learned_lessons with no lessons"""
        loki_mode.orchestrator.memory.memory_search = AsyncMock(return_value=[])
        result = await loki_mode._retrieve_learned_lessons("test query")
        assert result == ""

    @pytest.mark.asyncio
    async def test_retrieve_learned_lessons_with_lessons(self, loki_mode):
        """Test _retrieve_learned_lessons with lessons found"""
        lessons = [
            {"content": "Test lesson 1", "tags": []},
            {"content": "CRITICAL: Test lesson 2", "tags": ["critical"]},
        ]
        loki_mode.orchestrator.memory.memory_search = AsyncMock(return_value=lessons)
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="Distilled lessons")

        result = await loki_mode._retrieve_learned_lessons("test query")
        assert "Distilled lessons" in result
        loki_mode.orchestrator.llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_learned_lessons_many_lessons(self, loki_mode):
        """Test _retrieve_learned_lessons with many lessons (sliding window)"""
        lessons = [{"content": f"Lesson {i}", "tags": []} for i in range(25)]
        # Add some critical ones
        lessons[0]["content"] = "CRITICAL: Important lesson"
        lessons[0]["tags"] = ["critical"]

        loki_mode.orchestrator.memory.memory_search = AsyncMock(return_value=lessons)
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="Distilled")

        result = await loki_mode._retrieve_learned_lessons("test")
        # Should prioritize critical lessons
        assert "Distilled" in result

    @pytest.mark.asyncio
    async def test_run_parallel_review(self, loki_mode):
        """Test _run_parallel_review with mock agents"""
        code_results = ["code1", "code2"]
        memory_context = "context"

        # Mock SubAgent
        with patch("core.loki.SubAgent") as mock_subagent:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="review result")
            mock_subagent.return_value = mock_agent

            result = await loki_mode._run_parallel_review(code_results, memory_context)
            assert "Combined Review" in result
            assert mock_subagent.call_count == 3  # 3 reviewers
            mock_agent.run.assert_called()

    @pytest.mark.asyncio
    async def test_debate_memory_conflict_evolve(self, loki_mode):
        """Test _debate_memory_conflict with evolve decision"""
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="DECISION: EVOLVE - justification")
        loki_mode.orchestrator.memory.memory_write = AsyncMock()

        result = await loki_mode._debate_memory_conflict("conflict", ["impl"], "memory")
        assert result is True
        loki_mode.orchestrator.memory.memory_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_debate_memory_conflict_remediate(self, loki_mode):
        """Test _debate_memory_conflict with remediate decision"""
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="DECISION: REMEDIATE")

        result = await loki_mode._debate_memory_conflict("conflict", ["impl"], "memory")
        assert result is False
        loki_mode.orchestrator.memory.memory_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_loki_macro(self, loki_mode):
        """Test _save_loki_macro saves to memU"""
        prd = "test prd"
        tasks = [{"name": "task1"}]
        results = ["result1"]
        status = "success"

        await loki_mode._save_loki_macro(prd, tasks, results, status)
        loki_mode.orchestrator.adapters["memu"].learn_from_interaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_decompose_prd_success(self, loki_mode):
        """Test _decompose_prd with successful JSON parsing"""
        loki_mode.orchestrator.llm.generate = AsyncMock(
            return_value='[{"name": "test", "role": "dev", "task_description": "do it"}]'
        )

        result = await loki_mode._decompose_prd("test prd", "context")
        assert len(result) == 1
        assert result[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_decompose_prd_fallback(self, loki_mode):
        """Test _decompose_prd fallback when JSON parsing fails"""
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="invalid json")

        result = await loki_mode._decompose_prd("test prd")
        # Should return default task
        assert len(result) == 1
        assert result[0]["name"] == "Developer"

    @pytest.mark.asyncio
    async def test_execute_parallel_tasks(self, loki_mode):
        """Test _execute_parallel_tasks runs agents in parallel"""
        tasks = [{"name": "agent1", "role": "dev", "task_description": "task1"}]

        with patch("core.agents.SubAgent") as mock_subagent:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="result")
            mock_subagent.return_value = mock_agent

            results = await loki_mode._execute_parallel_tasks(tasks, "context")
            assert results == ["result"]
            mock_subagent.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_security_audit_pass(self, loki_mode):
        """Test _run_security_audit passes security checks"""
        results = ["clean code"]

        with patch("adapters.security.tirith_guard.guard.validate", return_value=True):
            result = await loki_mode._run_security_audit(results)
            assert "Passed" in result

    @pytest.mark.asyncio
    async def test_run_security_audit_fail_unicode(self, loki_mode):
        """Test _run_security_audit fails on suspicious unicode"""
        results = ["bad code with \u202e reversed"]

        with patch("adapters.security.tirith_guard.guard.validate", return_value=False):
            result = await loki_mode._run_security_audit(results)
            assert "FAILED" in result

    @pytest.mark.asyncio
    async def test_deploy_product(self, loki_mode):
        """Test _deploy_product returns skip message when no pipeline configured"""
        result = await loki_mode._deploy_product()
        assert "skipped" in result.lower() or "no pipeline" in result.lower()

    @pytest.mark.asyncio
    async def test_activate_full_pipeline_no_conflict(self, loki_mode):
        """Test activate with full pipeline, no memory conflicts"""
        prd_text = "Build a todo app"

        # Mock all the methods
        with (
            patch("core.loki.can_allocate", return_value=True),
            patch.object(loki_mode, "_retrieve_learned_lessons", new_callable=AsyncMock) as mock_retrieve,
            patch.object(loki_mode, "_decompose_prd", new_callable=AsyncMock) as mock_decompose,
            patch.object(loki_mode, "_execute_parallel_tasks", new_callable=AsyncMock) as mock_execute,
            patch.object(loki_mode, "_run_parallel_review", new_callable=AsyncMock) as mock_review,
            patch.object(loki_mode, "_run_security_audit", new_callable=AsyncMock) as mock_audit,
            patch.object(loki_mode, "_deploy_product", new_callable=AsyncMock) as mock_deploy,
            patch.object(loki_mode, "_save_loki_macro", new_callable=AsyncMock) as mock_save,
            patch.object(loki_mode, "_relay_status", new_callable=AsyncMock) as mock_relay,
        ):
            mock_retrieve.return_value = "memory context"
            mock_decompose.return_value = [{"name": "dev", "role": "Senior Dev", "task_description": "implement"}]
            mock_execute.return_value = ["code result"]
            mock_review.return_value = "review summary without conflict"
            mock_audit.return_value = "audit passed"
            mock_deploy.return_value = "deployed"
            mock_save.return_value = None

            result = await loki_mode.activate(prd_text)

            assert loki_mode.is_active is False  # Should be deactivated
            assert "complete" in result
            mock_relay.assert_called()
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_with_memory_conflict_remediation(self, loki_mode):
        """Test activate with memory conflict requiring remediation"""
        prd_text = "Build app"

        with (
            patch("core.loki.can_allocate", return_value=True),
            patch.object(loki_mode, "_retrieve_learned_lessons", new_callable=AsyncMock) as mock_retrieve,
            patch.object(loki_mode, "_decompose_prd", new_callable=AsyncMock) as mock_decompose,
            patch.object(loki_mode, "_execute_parallel_tasks", new_callable=AsyncMock) as mock_execute,
            patch.object(loki_mode, "_run_parallel_review", new_callable=AsyncMock) as mock_review,
            patch.object(loki_mode, "_debate_memory_conflict", new_callable=AsyncMock) as mock_debate,
            patch.object(loki_mode, "_run_security_audit", new_callable=AsyncMock) as mock_audit,
            patch.object(loki_mode, "_deploy_product", new_callable=AsyncMock) as mock_deploy,
            patch.object(loki_mode, "_save_loki_macro", new_callable=AsyncMock) as mock_save,
            patch.object(loki_mode, "_relay_status", new_callable=AsyncMock) as mock_relay,
        ):
            mock_retrieve.return_value = "memory context"
            mock_decompose.return_value = [{"name": "dev", "role": "Senior Dev", "task_description": "implement"}]
            mock_execute.return_value = ["code result"]
            mock_review.return_value = "MEMORY CONFLICT: some conflict"
            mock_debate.return_value = False  # Remediation needed
            mock_audit.return_value = "audit passed"
            mock_deploy.return_value = "deployed"

            result = await loki_mode.activate(prd_text)

            # Should have called execute twice (original + remediation)
            assert mock_execute.call_count == 2
            # Should have called review twice
            assert mock_review.call_count == 2

    @pytest.mark.asyncio
    async def test_activate_with_memory_conflict_evolution(self, loki_mode):
        """Test activate with memory conflict resolving to evolution (line 74)"""
        prd_text = "Build app"
        with (
            patch("core.loki.can_allocate", return_value=True),
            patch.object(loki_mode, "_retrieve_learned_lessons", new_callable=AsyncMock) as mock_retrieve,
            patch.object(loki_mode, "_decompose_prd", new_callable=AsyncMock) as mock_decompose,
            patch.object(loki_mode, "_execute_parallel_tasks", new_callable=AsyncMock) as mock_execute,
            patch.object(loki_mode, "_run_parallel_review", new_callable=AsyncMock) as mock_review,
            patch.object(loki_mode, "_debate_memory_conflict", new_callable=AsyncMock) as mock_debate,
            patch.object(loki_mode, "_run_security_audit", new_callable=AsyncMock) as mock_audit,
            patch.object(loki_mode, "_deploy_product", new_callable=AsyncMock) as mock_deploy,
            patch.object(loki_mode, "_save_loki_macro", new_callable=AsyncMock) as mock_save,
            patch.object(loki_mode, "_relay_status", new_callable=AsyncMock) as mock_relay,
        ):
            mock_retrieve.return_value = "memory context"
            mock_decompose.return_value = [{"name": "dev", "role": "Senior Dev", "task_description": "implement"}]
            mock_execute.return_value = ["code result"]
            mock_review.return_value = "MEMORY CONFLICT: some conflict"
            mock_debate.return_value = True  # Evolution! (line 74)
            mock_audit.return_value = "audit passed"
            mock_deploy.return_value = "deployed"

            await loki_mode.activate(prd_text)

            mock_relay.assert_any_call("✅ Mediation SUCCESS: Accepted as Architectural Evolution.")

    @pytest.mark.asyncio
    async def test_decompose_prd_json_parse_exception(self, loki_mode):
        """Test _decompose_prd with JSON parse exception (lines 288-289)"""
        loki_mode.orchestrator.llm.generate = AsyncMock(return_value="[invalid json]")

        # Patch json.loads to raise an exception
        with patch("json.loads", side_effect=ValueError("JSON Error")):
            result = await loki_mode._decompose_prd("test prd")
            # Should hit except block and return default
            assert len(result) == 1
            assert result[0]["name"] == "Developer"

    @pytest.mark.asyncio
    async def test_run_security_audit_secret_leak(self, loki_mode, caplog):
        """Test _run_security_audit with secret leak warning (line 341)"""
        import logging

        results = ["api_key = 'sk-12345'"]

        with patch("adapters.security.tirith_guard.guard.validate", return_value=True):
            with caplog.at_level(logging.DEBUG, logger="core.loki"):
                result = await loki_mode._run_security_audit(results)
                assert "Passed" in result
                # Check for warning log
                assert any("SECURITY WARNING: Potential secret leak detected" in r.message for r in caplog.records)


class TestDeployProduct:
    """Tests for LokiMode._deploy_product (Phase 3A graceful degradation)."""

    @pytest.fixture
    def loki(self):
        orchestrator = MagicMock()
        return LokiMode(orchestrator)

    @pytest.mark.asyncio
    async def test_deploy_script_success(self, loki):
        """Test deployment succeeds when script exits 0."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Deployed to staging"

        with patch.dict("os.environ", {"MEGABOT_DEPLOY_SCRIPT": "/tmp/deploy.sh"}):
            with patch("os.path.isfile", return_value=True):
                with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
                    result = await loki._deploy_product()

        assert "succeeded" in result.lower()
        assert "Deployed to staging" in result

    @pytest.mark.asyncio
    async def test_deploy_script_failure(self, loki):
        """Test deployment failure when script exits non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Build failed"

        with patch.dict("os.environ", {"MEGABOT_DEPLOY_SCRIPT": "/tmp/deploy.sh"}):
            with patch("os.path.isfile", return_value=True):
                with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
                    result = await loki._deploy_product()

        assert "failed" in result.lower()
        assert "exit 1" in result
        assert "Build failed" in result

    @pytest.mark.asyncio
    async def test_deploy_script_timeout(self, loki):
        """Test deployment timeout after 300 seconds."""
        with patch.dict("os.environ", {"MEGABOT_DEPLOY_SCRIPT": "/tmp/deploy.sh"}):
            with patch("os.path.isfile", return_value=True):
                with patch(
                    "asyncio.to_thread",
                    new_callable=AsyncMock,
                    side_effect=subprocess.TimeoutExpired(cmd="/tmp/deploy.sh", timeout=300),
                ):
                    result = await loki._deploy_product()

        assert "timed out" in result.lower()
        assert "300" in result

    @pytest.mark.asyncio
    async def test_deploy_script_general_exception(self, loki):
        """Test deployment handles general exceptions."""
        with patch.dict("os.environ", {"MEGABOT_DEPLOY_SCRIPT": "/tmp/deploy.sh"}):
            with patch("os.path.isfile", return_value=True):
                with patch(
                    "asyncio.to_thread",
                    new_callable=AsyncMock,
                    side_effect=OSError("Permission denied"),
                ):
                    result = await loki._deploy_product()

        assert "error" in result.lower()
        assert "Permission denied" in result

    @pytest.mark.asyncio
    async def test_deploy_no_script_env(self, loki):
        """Test deployment skipped when MEGABOT_DEPLOY_SCRIPT not set."""
        with patch.dict("os.environ", {}, clear=False):
            # Ensure the env var is absent
            import os

            os.environ.pop("MEGABOT_DEPLOY_SCRIPT", None)
            result = await loki._deploy_product()

        assert "skipped" in result.lower()

    @pytest.mark.asyncio
    async def test_deploy_script_not_a_file(self, loki):
        """Test deployment skipped when script path doesn't point to a file."""
        with patch.dict("os.environ", {"MEGABOT_DEPLOY_SCRIPT": "/nonexistent/deploy.sh"}):
            with patch("os.path.isfile", return_value=False):
                result = await loki._deploy_product()

        assert "skipped" in result.lower()
