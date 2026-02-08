import asyncio
import json
import logging
import subprocess
from typing import Any

from core.interfaces import ToolInterface

logger = logging.getLogger(__name__)


class MCPAdapter(ToolInterface):
    def __init__(self, server_config: dict[str, Any]):
        self.name = server_config["name"]
        self.command = server_config["command"]
        self.args = server_config.get("args", [])
        self.process = None
        self.tools: list[dict[str, Any]] = []
        self._request_id = 0

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Started MCP Server: %s", self.name)
        # Fetch tool list on startup
        try:
            res = await self.execute(method="tools/list")
            if res and "result" in res:
                self.tools = res["result"].get("tools", [])
                logger.info("Server '%s' provided %d tools.", self.name, len(self.tools))
        except Exception as e:
            logger.error("Failed to fetch tools for %s: %s", self.name, e)

    async def execute(self, **kwargs) -> Any:
        method = kwargs.get("method")
        params = kwargs.get("params", {})
        if not self.process:
            await self.start()

        self._request_id += 1
        request = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}

        if self.process and self.process.stdin:
            self.process.stdin.write(json.dumps(request).encode() + b"\n")
            await self.process.stdin.drain()

            if self.process.stdout:
                line = await self.process.stdout.readline()
                if line:
                    return json.loads(line.decode())
        return None


class MCPManager:
    def __init__(self, configs: list[dict[str, Any]]):
        self.servers = {cfg["name"]: MCPAdapter(cfg) for cfg in configs}

    async def start_all(self):
        for server in self.servers.values():
            await server.start()

    def find_server_for_tool(self, tool_name: str) -> str | None:
        """Find which MCP server provides the specified tool"""
        for server_name, adapter in self.servers.items():
            if any(t["name"] == tool_name for t in adapter.tools):
                return server_name
        return None

    async def call_tool(self, server_name: str | None, tool_name: str, params: dict[str, Any]):
        if not server_name:
            server_name = self.find_server_for_tool(tool_name)

        if not server_name:
            # Fallback to first server if only one is available
            if len(self.servers) == 1:
                server_name = list(self.servers.keys())[0]
            else:
                return {"error": f"Tool '{tool_name}' not found on any MCP server."}

        server = self.servers.get(server_name)
        if server:
            return await server.execute(method="tools/call", params={"name": tool_name, "arguments": params})
        return {"error": f"Server '{server_name}' not found."}
