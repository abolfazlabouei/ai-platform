"""
McpClientPool: maintains connections to registered MCP servers using
langchain-mcp-adapters, and exposes both:
  - discover_tools(server) -> used by /test-connection to populate McpTool cache
  - as_langchain_tools(server_ids, approved_tool_names) -> tools bindable to the model
  - call_tool(tool_name, arguments) -> direct invocation used by tool_exec_node

A process-wide pool is kept so repeated requests to the same server reuse the
session instead of reconnecting every turn.

Servers with auth_config {"type": "sandbox"} (code-sandbox-service) need per-conversation
identity: each request carries X-Sandbox-Key plus a short-lived X-Sandbox-Context JWT naming
the conversation and user. Their clients/tools are therefore cached per
(server_id, conversation_id) and rebuilt before the token expires, never shared across
conversations.
"""
from __future__ import annotations

import time
from typing import Any

import jwt

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import settings
from app.models.mcp_server import McpServer


SANDBOX_AUTH_TYPE = "sandbox"
# code-sandbox-service rejects contexts valid for more than 5 minutes; rebuild well before expiry.
SANDBOX_CONTEXT_LIFETIME_SECONDS = 300
SANDBOX_CLIENT_TTL_SECONDS = 120


def mint_sandbox_context(conversation_id: str, user_id: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    return jwt.encode(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "iat": issued,
            "exp": issued + SANDBOX_CONTEXT_LIFETIME_SECONDS,
        },
        settings.SANDBOX_CONTEXT_SECRET,
        algorithm="HS256",
    )


def _input_schema(tool: Any) -> dict:
    """JSON schema of an MCP tool's arguments. langchain-mcp-adapters 0.0.x exposed a pydantic model as
    `args_schema`; 0.1.x exposes the JSON-schema dict itself."""
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return {}
    if isinstance(schema, dict):
        return schema
    return schema.model_json_schema()


def to_tool_schema(tool: Any) -> dict:
    """OpenAI-format function schema of an MCP tool, as plain data.

    The runtime config is checkpointed by LangGraph (msgpack), which cannot serialize live tool objects
    ("Type is not msgpack serializable: StructuredTool"). The model only needs the schema to bind the tool;
    execution goes by name through McpClientPool.call_tool, so nothing else is needed from the object."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": _input_schema(tool) or {"type": "object", "properties": {}},
        },
    }


def _is_sandbox(server: McpServer) -> bool:
    return server.auth_config.get("type") == SANDBOX_AUTH_TYPE


class McpClientPool:
    _instance: "McpClientPool | None" = None

    def __new__(cls) -> "McpClientPool":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}  # server_id -> MultiServerMCPClient
            # (conversation_id | None, tool_name) -> bound structured tool. Only sandbox-type
            # servers use a conversation_id, so their tools never leak across conversations.
            cls._instance._tool_cache = {}
            # (server_id, conversation_id) -> ({tool_name: tool}, built_at, server)
            cls._instance._sandbox_clients = {}
        return cls._instance

    def _connection_config(
        self,
        server: McpServer,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        cfg: dict[str, Any] = {"url": server.url, "transport": server.transport.value}
        if server.auth_config.get("type") == "bearer":
            cfg["headers"] = {"Authorization": f"Bearer {server.auth_config['token']}"}
        elif _is_sandbox(server):
            cfg["headers"] = {
                "X-Sandbox-Key": settings.SANDBOX_SHARED_SECRET,
                "X-Sandbox-Context": mint_sandbox_context(
                    conversation_id or "test-connection", user_id or server.user_id
                ),
            }
        return cfg

    async def discover_tools(self, server: McpServer) -> list[dict]:
        """Connects, lists tools, and returns raw MCP tool specs (name/description/input_schema)."""
        client = MultiServerMCPClient({server.name: self._connection_config(server)})
        tools = await client.get_tools()
        specs = []
        for t in tools:
            specs.append(
                {
                    "tool_name": t.name,
                    "description": t.description,
                    "input_schema": _input_schema(t),
                }
            )
        if not _is_sandbox(server):  # sandbox tools are cached per conversation instead
            self._clients[str(server.id)] = client
            for t in tools:
                self._tool_cache[(None, t.name)] = t
        return specs

    async def _sandbox_tools(self, server: McpServer, conversation_id: str, user_id: str) -> dict[str, Any]:
        """Tools of a sandbox-type server bound to this conversation; rebuilt before the context JWT expires."""
        key = (str(server.id), conversation_id)
        cached = self._sandbox_clients.get(key)
        if cached and time.monotonic() - cached[1] < SANDBOX_CLIENT_TTL_SECONDS:
            return cached[0]
        client = MultiServerMCPClient(
            {server.name: self._connection_config(server, conversation_id=conversation_id, user_id=user_id)}
        )
        tools = {t.name: t for t in await client.get_tools()}
        self._sandbox_clients[key] = (tools, time.monotonic(), server)
        # Drop expired entries so abandoned conversations do not accumulate.
        now = time.monotonic()
        for k in [k for k, v in self._sandbox_clients.items() if now - v[1] > 10 * SANDBOX_CLIENT_TTL_SECONDS]:
            del self._sandbox_clients[k]
        return tools

    async def as_langchain_tools(
        self,
        servers: list[McpServer],
        approved_tool_names: set[str],
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> list[Any]:
        """Connects to each server (if not already connected) and returns only approved tools."""
        all_tools: list[Any] = []
        for server in servers:
            if _is_sandbox(server):
                if not conversation_id or not user_id:
                    continue  # no identity, no sandbox tools
                tools = list((await self._sandbox_tools(server, conversation_id, user_id)).values())
            else:
                key = str(server.id)
                if key not in self._clients:
                    await self.discover_tools(server)
                tools = await self._clients[key].get_tools()
            all_tools.extend(t for t in tools if t.name in approved_tool_names)
        return all_tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> Any:
        tool = None
        if conversation_id and user_id:
            # Sandbox tools: refresh the client (and its context JWT) if it aged out while the graph
            # was paused, e.g. waiting for human approval.
            for (server_id, conv), (tools, _, server) in list(self._sandbox_clients.items()):
                if conv == conversation_id and tool_name in tools:
                    tool = (await self._sandbox_tools(server, conversation_id, user_id))[tool_name]
                    break
        if tool is None:
            tool = self._tool_cache.get((None, tool_name))
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' is not connected/cached in this process")
        return await tool.ainvoke(arguments, config={"timeout": settings.MCP_TOOL_CALL_TIMEOUT_SECONDS})
