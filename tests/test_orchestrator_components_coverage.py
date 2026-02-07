import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from core.orchestrator_components import MessageHandler, HealthMonitor, BackgroundTasks


class BreakLoop(BaseException):
    pass


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.memory = AsyncMock()
    orch.admin_handler = AsyncMock()
    orch.adapters = {
        "openclaw": AsyncMock(),
        "messaging": MagicMock(clients=[]),
        "mcp": AsyncMock(servers=[]),
        "memu": AsyncMock(),
    }
    orch.mode = "plan"
    orch.send_platform_message = AsyncMock()
    orch.restart_component = AsyncMock()
    return orch


@pytest.mark.asyncio
async def test_message_handler_full(mock_orchestrator):
    handler = MessageHandler(mock_orchestrator)
    mock_orchestrator.memory.get_unified_id.return_value = "u1"
    mock_orchestrator.memory.chat_read.return_value = []

    # process_gateway_message
    await handler.process_gateway_message(
        {"type": "message", "content": "hi", "sender_id": "s1"}
    )
    assert mock_orchestrator.memory.chat_write.called

    # _process_attachments
    mock_driver = AsyncMock()
    mock_driver.execute.return_value = "cat"

    # Reset the cached driver so our mock is used instead of the
    # real ComputerDriver resolved during process_gateway_message above
    handler._computer_driver = mock_driver

    res = await handler._process_attachments(
        [{"type": "image", "data": "d"}], "s1", "c"
    )
    assert "cat" in res or "cat" in str(res)

    # _update_chat_context
    await handler._update_chat_context("chat1", "hello")
    assert "chat1" in handler.chat_contexts


@pytest.mark.asyncio
async def test_health_monitor_all_paths(mock_orchestrator):
    monitor = HealthMonitor(mock_orchestrator)

    # Success
    mock_orchestrator.memory.memory_stats.return_value = {}
    mock_orchestrator.adapters["openclaw"].websocket = MagicMock()
    mock_orchestrator.adapters["messaging"].clients = []
    mock_orchestrator.adapters["mcp"].servers = []
    health = await monitor.get_system_health()
    assert health["memory"]["status"] == "up"

    # Failures
    mock_orchestrator.memory.memory_stats.side_effect = Exception("Err")
    del mock_orchestrator.adapters["openclaw"].websocket
    health = await monitor.get_system_health()
    assert health["memory"]["status"] == "down"

    # Monitoring loop
    with patch.object(
        monitor,
        "get_system_health",
        side_effect=[{"c": {"status": "down"}}, BreakLoop()],
    ):
        with patch("asyncio.sleep", side_effect=[None, BreakLoop()]):
            try:
                await monitor.start_monitoring()
            except BreakLoop:
                pass
    assert mock_orchestrator.restart_component.called


@pytest.mark.asyncio
async def test_background_tasks_all_loops(mock_orchestrator):
    tasks = BackgroundTasks(mock_orchestrator)
    mock_orchestrator.user_identity = AsyncMock()
    mock_orchestrator.chat_memory = AsyncMock()
    mock_orchestrator.knowledge_memory = AsyncMock()
    mock_orchestrator.memory.get_all_chat_ids.return_value = ["c1"]

    with patch("asyncio.sleep", side_effect=[BreakLoop(), BreakLoop(), BreakLoop()]):
        # sync_loop
        try:
            await tasks.sync_loop()
        except BreakLoop:
            pass
        # pruning_loop
        try:
            await tasks.pruning_loop()
        except BreakLoop:
            pass
        # backup_loop
        try:
            await tasks.backup_loop()
        except BreakLoop:
            pass

    assert mock_orchestrator.user_identity.sync_pending_identities.called
    assert mock_orchestrator.memory.chat_forget.called


@pytest.mark.asyncio
async def test_background_tasks_proactive_loop_success(mock_orchestrator):
    tasks = BackgroundTasks(mock_orchestrator)
    mock_orchestrator.adapters["memu"].get_anticipations.return_value = [
        {"content": "task"}
    ]
    mock_orchestrator.adapters["mcp"].call_tool.return_value = ["event"]
    with patch("asyncio.sleep", side_effect=[BreakLoop(), BreakLoop(), BreakLoop()]):
        try:
            await tasks.proactive_loop()
        except BreakLoop:
            pass
    assert mock_orchestrator.adapters["openclaw"].send_message.called
