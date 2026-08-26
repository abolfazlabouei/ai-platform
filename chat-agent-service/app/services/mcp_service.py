"""
mcp_service: business logic for registering MCP servers, testing connections
(discover + cache tools), and the approve/reject workflow for individual tools.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp_manager.client_pool import McpClientPool
from app.models.mcp_server import McpServer, McpServerStatus, McpTool, ToolApprovalStatus
from app.repositories.mcp_repo import McpRepo


class McpService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = McpRepo(db)

    async def create_server(self, user_id: str, name: str, transport: str, url: str, auth_config: dict) -> McpServer:
        return await self.repo.create_server(
            user_id=user_id, name=name, transport=transport, url=url, auth_config=auth_config
        )

    async def list_servers(self, user_id: str) -> list[McpServer]:
        return await self.repo.list_servers(user_id)

    async def delete_server(self, server: McpServer) -> None:
        await self.repo.delete_server(server)

    async def test_connection(self, server: McpServer) -> McpServer:
        """Connects to the server, discovers tools, and caches them (status=pending by default)."""
        pool = McpClientPool()
        try:
            tool_specs = await pool.discover_tools(server)
            await self.repo.replace_tools(server.id, tool_specs)
            return await self.repo.update_server(
                server, status=McpServerStatus.CONNECTED, last_error=None, last_tested_at=datetime.now(UTC)
            )
        except Exception as exc:  # noqa: BLE001
            return await self.repo.update_server(
                server, status=McpServerStatus.ERROR, last_error=str(exc), last_tested_at=datetime.now(UTC)
            )

    async def list_tools(self, server_id: uuid.UUID) -> list[McpTool]:
        return await self.repo.list_tools(server_id)

    async def set_tool_approval(self, tool: McpTool, status: ToolApprovalStatus, requires_hitl: bool) -> McpTool:
        return await self.repo.update_tool(tool, approval_status=status, requires_hitl=requires_hitl)
