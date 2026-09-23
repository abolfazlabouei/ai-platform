"""
McpClientPool: maintains connections to registered MCP servers using
langchain-mcp-adapters, and exposes both:
  - discover_tools(server) -> used by /test-connection to populate McpTool cache
  - as_langchain_tools(server_ids, approved_tool_names) -> tools bindable to the model
  - call_tool(tool_name, arguments) -> direct invocation used by tool_exec_node

A process-wide pool is kept so repeated requests to the same server reuse the
session instead of reconnecting every turn.
"""
from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import settings
from app.models.mcp_server import McpServer


class McpClientPool:
    _instance: "McpClientPool | None" = None

    def __new__(cls) -> "McpClientPool":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}  # server_id -> MultiServerMCPClient
            cls._instance._tool_cache = {}  # tool_name -> bound structured tool
        return cls._instance

    def _connection_config(self, server: McpServer, token: str | None = None) -> dict[str, Any]:
        cfg: dict[str, Any] = {"url": server.url, "transport": server.transport.value}
        headers = {}
        if server.auth_config.get("type") == "bearer":
            headers["Authorization"] = f"Bearer {server.auth_config['token']}"
        elif server.auth_config.get("type") == "oauth2_per_user" and token:
            headers["Authorization"] = f"Bearer {token}"
        headers.update(server.auth_config.get("custom_headers", {}))
        if headers:
            cfg["headers"] = headers
        return cfg

    async def discover_tools(self, server: McpServer) -> list[dict]:
        """Connects, lists tools, and returns raw MCP tool specs (name/description/input_schema)."""
        client = MultiServerMCPClient({server.name: self._connection_config(server)})
        tools = client.get_tools()
        self._clients[str(server.id)] = client
        specs = []
        for t in tools:
            specs.append(
                {
                    "tool_name": t.name,
                    "description": t.description,
                    "input_schema": t.args_schema.model_json_schema() if t.args_schema else {},
                }
            )
            self._tool_cache[t.name] = t
        return specs

    async def as_langchain_tools(self, servers: list[McpServer], approved_tool_names: set[str]) -> list[Any]:
        """Connects to each server (if not already connected) and returns only approved tools."""
        all_tools: list[Any] = []
        for server in servers:
            key = str(server.id)
            if key not in self._clients:
                await self.discover_tools(server)
            client = self._clients[key]
            tools = client.get_tools()
            all_tools.extend(t for t in tools if t.name in approved_tool_names)
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        tool = self._tool_cache.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' is not connected/cached in this process")
        return await tool.ainvoke(arguments, config={"timeout": settings.MCP_TOOL_CALL_TIMEOUT_SECONDS})
