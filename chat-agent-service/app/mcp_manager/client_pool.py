"""
McpClientPool: maintains connections to registered MCP servers using
langchain-mcp-adapters, and exposes both:
  - discover_tools(server) -> used by /test-connection to populate McpTool cache
  - as_langchain_tools(servers, approved_tool_names, user_id) -> tools bindable to the model
  - call_tool(tool_name, arguments, user_id) -> direct invocation used by tool_exec_node

For bearer-token servers, connections are keyed by server_id and reused.
For oauth2_per_user servers, connections are keyed by (server_id, user_id),
using each user's freshly verified access token.
"""
from __future__ import annotations

from typing import Any
import uuid

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import settings
from app.models.mcp_server import McpServer


class McpClientPool:
    _instance: "McpClientPool | None" = None

    def __new__(cls) -> "McpClientPool":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}  # key -> MultiServerMCPClient
            cls._instance._tool_cache = {}  # tool_name or (tool_name, user_id) -> tool
            cls._instance._tool_server_map = {}  # tool_name -> McpServer
        return cls._instance

    def _connection_config(self, server: McpServer, token: str | None = None) -> dict[str, Any]:
        cfg: dict[str, Any] = {"url": server.url, "transport": server.transport.value}
        if server.auth_config.get("type") == "bearer":
            cfg["headers"] = {"Authorization": f"Bearer {server.auth_config['token']}"}
        elif server.auth_config.get("type") == "oauth2_per_user" and token:
            cfg["headers"] = {"Authorization": f"Bearer {token}"}
        return cfg

    async def discover_tools(self, server: McpServer, user_id: str | None = None) -> list[dict]:
        """Connects, lists tools, and returns raw MCP tool specs (name/description/input_schema)."""
        token = None
        if server.auth_config.get("type") == "oauth2_per_user" and user_id:
            from app.services.oauth_service import oauth_service

            token = await oauth_service.get_valid_access_token(server.id, user_id)
            if not token:
                return []

        client = MultiServerMCPClient({server.name: self._connection_config(server, token=token)})
        tools = await client.get_tools()

        key: Any = (str(server.id), user_id) if (server.auth_config.get("type") == "oauth2_per_user" and user_id) else str(server.id)
        self._clients[key] = client

        specs = []
        for t in tools:
            specs.append(
                {
                    "tool_name": t.name,
                    "description": t.description,
                    "input_schema": t.args_schema.model_json_schema() if t.args_schema else {},
                }
            )
            if user_id:
                self._tool_cache[(t.name, user_id)] = t
            self._tool_cache[t.name] = t
            self._tool_server_map[t.name] = server
        return specs

    async def as_langchain_tools(
        self, servers: list[McpServer], approved_tool_names: set[str], user_id: str | None = None
    ) -> list[Any]:
        """Connects to each server (if not already connected) and returns only approved tools."""
        all_tools: list[Any] = []
        for server in servers:
            if server.auth_config.get("type") == "oauth2_per_user":
                if not user_id:
                    continue
                cache_key = (str(server.id), user_id)

                from app.services.oauth_service import oauth_service

                token = await oauth_service.get_valid_access_token(server.id, user_id)
                if token is None:
                    continue

                client = MultiServerMCPClient({server.name: self._connection_config(server, token=token)})
                self._clients[cache_key] = client
                tools = await client.get_tools()
                for t in tools:
                    self._tool_cache[(t.name, user_id)] = t
                    self._tool_cache[t.name] = t
                    self._tool_server_map[t.name] = server
                all_tools.extend(t for t in tools if t.name in approved_tool_names)
            else:
                key = str(server.id)
                if key not in self._clients:
                    await self.discover_tools(server)
                client = self._clients[key]
                tools = await client.get_tools()
                for t in tools:
                    self._tool_cache[t.name] = t
                    self._tool_server_map[t.name] = server
                all_tools.extend(t for t in tools if t.name in approved_tool_names)
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict, user_id: str | None = None) -> Any:
        tool = None
        server = self._tool_server_map.get(tool_name)

        if server and server.auth_config.get("type") == "oauth2_per_user" and user_id:
            from app.services.oauth_service import oauth_service

            token = await oauth_service.get_valid_access_token(server.id, user_id)
            if token is None:
                raise ValueError(f"OAuth token expired or missing for tool '{tool_name}' and user '{user_id}'")

            cache_key = (str(server.id), user_id)
            client = MultiServerMCPClient({server.name: self._connection_config(server, token=token)})
            self._clients[cache_key] = client
            tools = await client.get_tools()
            for t in tools:
                self._tool_cache[(t.name, user_id)] = t
                if t.name == tool_name:
                    tool = t

        if tool is None and user_id:
            tool = self._tool_cache.get((tool_name, user_id))
        if tool is None:
            tool = self._tool_cache.get(tool_name)

        if tool is None:
            raise ValueError(f"Tool '{tool_name}' is not connected/cached in this process")
        return await tool.ainvoke(arguments, config={"timeout": settings.MCP_TOOL_CALL_TIMEOUT_SECONDS})
