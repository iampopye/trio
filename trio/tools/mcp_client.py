"""MCP (Model Context Protocol) client — connect external tool servers."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import json
import logging
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """Wrapper for a tool exposed by an MCP server."""

    def __init__(self, tool_name: str, tool_description: str, tool_schema: dict, server: "MCPServer"):
        self._name = tool_name
        self._description = tool_description
        self._parameters = tool_schema
        self._server = server

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            result = await self._server.call_tool(self._name, params)
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"MCP tool error: {e}", success=False)


class MCPServer:
    """Connection to an MCP server (stdio or HTTP transport)."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.transport = config.get("transport", "stdio")
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}

    async def start(self) -> None:
        """Start the MCP server process (stdio transport)."""
        if self.transport == "stdio":
            command = self.config.get("command", "")
            args = self.config.get("args", [])
            env = {**dict(__import__("os").environ), **self.config.get("env", {})}

            self._process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            # Start reading responses
            asyncio.create_task(self._read_responses())

            # Initialize
            await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "trio", "version": "0.1.0"},
            })
            logger.info(f"MCP server '{self.name}' started (stdio)")

    async def stop(self) -> None:
        if self._process:
            self._process.terminate()
            await self._process.wait()

    async def discover_tools(self) -> list[dict]:
        """Get available tools from the MCP server."""
        try:
            result = await self._send_request("tools/list", {})
            return result.get("tools", [])
        except Exception as e:
            logger.error(f"MCP tool discovery failed for '{self.name}': {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # Extract text content
        contents = result.get("content", [])
        texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
        return "\n".join(texts) if texts else str(result)

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request to the server."""
        if not self._process or not self._process.stdin:
            raise RuntimeError(f"MCP server '{self.name}' not running")

        self._request_id += 1
        req_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        data = json.dumps(request) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"MCP request '{method}' timed out")

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from stdout."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode().strip())
                req_id = data.get("id")

                if req_id and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if data.get("error"):
                        future.set_exception(RuntimeError(str(data["error"])))
                    else:
                        future.set_result(data.get("result", {}))

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"MCP response read error: {e}")
                break


class MCPManager:
    """Manages all MCP server connections."""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}

    async def start_servers(self, mcp_config: dict) -> list[BaseTool]:
        """Start all configured MCP servers and return discovered tools."""
        tools = []

        for name, server_config in mcp_config.items():
            try:
                server = MCPServer(name, server_config)
                await server.start()
                self._servers[name] = server

                # Discover tools
                server_tools = await server.discover_tools()
                for tool_def in server_tools:
                    mcp_tool = MCPTool(
                        tool_name=f"{name}_{tool_def['name']}",
                        tool_description=tool_def.get("description", ""),
                        tool_schema=tool_def.get("inputSchema", {}),
                        server=server,
                    )
                    tools.append(mcp_tool)
                    logger.info(f"Discovered MCP tool: {name}_{tool_def['name']}")

            except Exception as e:
                logger.error(f"Failed to start MCP server '{name}': {e}")

        return tools

    async def stop_all(self) -> None:
        for server in self._servers.values():
            await server.stop()
        self._servers.clear()
