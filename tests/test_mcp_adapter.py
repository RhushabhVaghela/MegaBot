import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from megabot.adapters.mcp_adapter import MCPAdapter, MCPManager


@pytest.mark.asyncio
async def test_mcp_adapter_execute():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock()
        mock_exec.return_value = mock_process
        mock_process.stdout.readline.return_value = json.dumps({"jsonrpc": "2.0", "result": "ok"}).encode() + b"\n"

        adapter = MCPAdapter({"name": "test", "command": "npx", "args": ["test-server"]})
        result = await adapter.execute(method="tools/list")

        assert mock_exec.called
        assert mock_process.stdin.write.called
        assert result["result"] == "ok"


@pytest.mark.asyncio
async def test_mcp_adapter_start():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock(
            return_value=json.dumps({"jsonrpc": "2.0", "result": {"tools": []}}).encode() + b"\n"
        )
        mock_exec.return_value = mock_process

        adapter = MCPAdapter({"name": "test", "command": "npx"})
        await adapter.start()
        assert mock_exec.called


@pytest.mark.asyncio
async def test_mcp_adapter_execute_no_stdout():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock()
        mock_exec.return_value = mock_process
        mock_process.stdout.readline.return_value = b""

        adapter = MCPAdapter({"name": "test", "command": "npx"})
        result = await adapter.execute(method="test")
        assert result is None


@pytest.mark.asyncio
async def test_mcp_manager_call_tool():
    with patch("megabot.adapters.mcp_adapter.MCPAdapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = {"result": "success"}

        manager = MCPManager([{"name": "test-server", "command": "npx"}])
        manager.servers["test-server"].process = MagicMock()

        result = await manager.call_tool("test-server", "test-tool", {"arg1": "val1"})

        assert result["result"] == "success"
        mock_execute.assert_called_once_with(
            method="tools/call",
            params={"name": "test-tool", "arguments": {"arg1": "val1"}},
        )


@pytest.mark.asyncio
async def test_mcp_manager_call_tool_not_found():
    manager = MCPManager([])
    result = await manager.call_tool("none", "none", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_mcp_manager_start_all():
    manager = MCPManager([{"name": "s1", "command": "c1"}, {"name": "s2", "command": "c2"}])
    for s in manager.servers.values():
        s.start = AsyncMock()

    await manager.start_all()
    for s in manager.servers.values():
        assert s.start.called


@pytest.mark.asyncio
async def test_mcp_adapter_fetch_tools_success():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock()
        mock_exec.return_value = mock_process
        mock_process.stdout.readline.return_value = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "result": {"tools": [{"name": "tool1"}, {"name": "tool2"}]},
                }
            ).encode()
            + b"\n"
        )

        adapter = MCPAdapter({"name": "test", "command": "npx"})
        await adapter.start()
        assert len(adapter.tools) == 2
        assert adapter.tools[0]["name"] == "tool1"


@pytest.mark.asyncio
async def test_mcp_manager_find_server_for_tool():
    manager = MCPManager([{"name": "s1", "command": "c1"}, {"name": "s2", "command": "c2"}])
    manager.servers["s1"].tools = [{"name": "tool1"}]
    manager.servers["s2"].tools = [{"name": "tool2"}]

    assert manager.find_server_for_tool("tool1") == "s1"
    assert manager.find_server_for_tool("tool2") == "s2"
    assert manager.find_server_for_tool("tool3") is None


@pytest.mark.asyncio
async def test_mcp_manager_call_tool_lookup():
    with patch("megabot.adapters.mcp_adapter.MCPAdapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = {"result": "ok"}
        manager = MCPManager([{"name": "s1", "command": "c1"}])
        manager.servers["s1"].tools = [{"name": "tool1"}]
        manager.servers["s1"].process = MagicMock()

        result = await manager.call_tool(None, "tool1", {})
        assert result["result"] == "ok"


@pytest.mark.asyncio
async def test_mcp_manager_call_tool_fallback():
    # One server fallback
    manager = MCPManager([{"name": "s1", "command": "c1"}])
    manager.servers["s1"].execute = AsyncMock(return_value={"result": "fallback_ok"})
    result = await manager.call_tool(None, "unknown_tool", {})
    assert result["result"] == "fallback_ok"

    # Multiple servers, no fallback
    manager = MCPManager([{"name": "s1", "command": "c1"}, {"name": "s2", "command": "c2"}])
    result = await manager.call_tool(None, "unknown_tool", {})
    assert "error" in result
    assert "not found on any MCP server" in result["error"]


@pytest.mark.asyncio
async def test_mcp_adapter_request_id_starts_at_zero():
    """Test that _request_id starts at 0."""
    adapter = MCPAdapter({"name": "test", "command": "npx"})
    assert adapter._request_id == 0


@pytest.mark.asyncio
async def test_mcp_adapter_request_id_increments():
    """Test that _request_id increments on each execute() call."""
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock(
            return_value=json.dumps({"jsonrpc": "2.0", "result": "ok"}).encode() + b"\n"
        )
        mock_exec.return_value = mock_process

        adapter = MCPAdapter({"name": "test", "command": "npx"})
        adapter.process = mock_process  # skip start()

        await adapter.execute(method="tools/list")
        assert adapter._request_id == 1

        await adapter.execute(method="tools/call")
        assert adapter._request_id == 2

        await adapter.execute(method="tools/list")
        assert adapter._request_id == 3


@pytest.mark.asyncio
async def test_mcp_adapter_request_id_in_payload():
    """Test that the incremented _request_id is included in the JSON-RPC request."""
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout.readline = AsyncMock(
            return_value=json.dumps({"jsonrpc": "2.0", "result": "ok"}).encode() + b"\n"
        )
        mock_exec.return_value = mock_process

        adapter = MCPAdapter({"name": "test", "command": "npx"})
        adapter.process = mock_process

        await adapter.execute(method="ping")

        # Verify the written payload contains id=1
        written_bytes = mock_process.stdin.write.call_args[0][0]
        payload = json.loads(written_bytes.strip())
        assert payload["id"] == 1
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "ping"
