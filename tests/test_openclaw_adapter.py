import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch
from adapters.openclaw_adapter import OpenClawAdapter
from core.interfaces import Message


@pytest.mark.asyncio
async def test_openclaw_adapter_connect():
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_connect.return_value = mock_ws
        mock_ws.recv.return_value = json.dumps({"type": "res", "id": "1", "result": {"status": "ok"}})
        adapter = OpenClawAdapter("localhost", 18789)
        await adapter.connect()
        assert mock_connect.called


@pytest.mark.asyncio
async def test_openclaw_adapter_send_message():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = AsyncMock()
    # Mock execute_tool since send_message calls it
    adapter.execute_tool = AsyncMock()
    msg = Message(content="test", sender="user")
    await adapter.send_message(msg)
    assert adapter.execute_tool.called


@pytest.mark.asyncio
async def test_openclaw_adapter_receive_message():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = AsyncMock()
    adapter.websocket.recv.return_value = json.dumps({"type": "event", "payload": {"content": "hi", "sender": "bot"}})
    msg = await adapter.receive_message()
    assert msg.content == "hi"


@pytest.mark.asyncio
async def test_openclaw_adapter_execute_tool():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = AsyncMock()

    # Mock result
    expected_res = {"type": "res", "id": "1", "result": "ok"}

    with patch("uuid.uuid4", return_value="1"):
        with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = expected_res
            result = await adapter.execute_tool("t", {})
            assert result.get("result") == "ok"


@pytest.mark.asyncio
async def test_openclaw_adapter_listen():
    adapter = OpenClawAdapter("localhost", 18789)
    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [json.dumps({"type": "event", "id": "none", "method": "chat.message"})]
    adapter.websocket = mock_ws
    event_received = asyncio.Event()

    async def on_event(data):
        event_received.set()

    adapter.on_event = on_event
    listen_task = asyncio.create_task(adapter._listen())
    await asyncio.wait_for(event_received.wait(), timeout=1.0)
    listen_task.cancel()


@pytest.mark.asyncio
async def test_openclaw_adapter_subscribe():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.execute_tool = AsyncMock()
    await adapter.subscribe_events(["e1"])
    assert adapter.execute_tool.called


@pytest.mark.asyncio
async def test_openclaw_adapter_connect_failure():
    with patch("websockets.connect", side_effect=Exception("failed")):
        adapter = OpenClawAdapter("localhost", 18789)
        with pytest.raises(Exception):
            await adapter.connect()


@pytest.mark.asyncio
async def test_openclaw_adapter_listen_error():
    adapter = OpenClawAdapter("localhost", 18789)
    mock_ws = AsyncMock()
    mock_ws.__aiter__.side_effect = ConnectionError("err")
    adapter.websocket = mock_ws
    await adapter._listen()
    assert True


@pytest.mark.asyncio
async def test_openclaw_adapter_receive_message_no_ws():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = None
    mock_ws = AsyncMock()
    mock_ws.recv.return_value = json.dumps({"type": "event", "payload": {"content": "ok", "sender": "bot"}})
    adapter.websocket = mock_ws
    msg = await adapter.receive_message()
    assert msg.content == "ok"


@pytest.mark.asyncio
async def test_openclaw_adapter_execute_tool_fail_connect():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = None
    with patch.object(adapter, "connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = None  # Ensure it doesn't set websocket
        result = await adapter.execute_tool("t", {})
        assert "error" in result


@pytest.mark.asyncio
async def test_openclaw_adapter_listen_error_v2():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = AsyncMock()
    # Mock the async iterator to raise an exception
    adapter.websocket.__aiter__.side_effect = ConnectionError("stream failed")
    # Should not crash, just catch and print
    await adapter._listen()
    assert True


@pytest.mark.asyncio
async def test_openclaw_adapter_receive_message_error():
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = None
    # Test line 122: when connect is called but websocket remains None
    with patch.object(adapter, "connect", new_callable=AsyncMock):
        msg = await adapter.receive_message()
        assert msg.sender == "error"


@pytest.mark.asyncio
async def test_openclaw_adapter_listen_no_websocket():
    """Test line 50: _listen returns early when websocket is None"""
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = None
    # Should return immediately without error
    result = await adapter._listen()
    assert result is None


@pytest.mark.asyncio
async def test_openclaw_adapter_listen_response_handling():
    """Test lines 57-60: Future handling when response received"""
    adapter = OpenClawAdapter("localhost", 18789)
    mock_ws = AsyncMock()

    # Create a real future and add it to pending_requests
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    adapter.pending_requests["test-id"] = future

    # Mock the response with matching ID
    mock_ws.__aiter__.return_value = [json.dumps({"type": "res", "id": "test-id", "result": "done"})]
    adapter.websocket = mock_ws

    # Run _listen for a short time to process the message
    listen_task = asyncio.create_task(adapter._listen())

    # Wait for the future to complete
    try:
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result["result"] == "done"
    except asyncio.TimeoutError:
        listen_task.cancel()
        pytest.fail("Future was not completed")

    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_openclaw_adapter_listen_already_done_future():
    """Test line 59: Future already done, should not set result"""
    adapter = OpenClawAdapter("localhost", 18789)
    mock_ws = AsyncMock()

    # Create a future that's already done
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    future.set_result("already done")
    adapter.pending_requests["test-id"] = future

    # Mock the response with matching ID - should not raise error
    mock_ws.__aiter__.return_value = [json.dumps({"type": "res", "id": "test-id", "result": "new"})]
    adapter.websocket = mock_ws

    # Run _listen - should handle already-done future gracefully
    listen_task = asyncio.create_task(adapter._listen())
    await asyncio.sleep(0.1)
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_openclaw_adapter_execute_tool_timeout():
    """Test lines 93-95: TimeoutError handling"""
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.websocket = AsyncMock()

    with patch("uuid.uuid4", return_value="timeout-test"):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await adapter.execute_tool("test_method", {"param": "value"})
            assert result["error"] == "Request timed out"
            assert result["type"] == "res"
            assert result["id"] == "timeout-test"


@pytest.mark.asyncio
async def test_openclaw_adapter_schedule_task():
    """Test line 122: schedule_task method"""
    adapter = OpenClawAdapter("localhost", 18789)
    adapter.execute_tool = AsyncMock(return_value={"status": "scheduled"})

    result = await adapter.schedule_task(
        name="daily_backup", schedule="0 0 * * *", method="files.backup", params={"path": "/data"}
    )

    adapter.execute_tool.assert_called_once_with(
        "cron.add",
        {"name": "daily_backup", "schedule": "0 0 * * *", "method": "files.backup", "params": {"path": "/data"}},
    )
    assert result["status"] == "scheduled"
