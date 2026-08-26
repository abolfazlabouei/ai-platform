"""Async CRUD queries for McpServer + McpTool."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_server import McpServer, McpTool


class McpRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_server(self, **kwargs) -> McpServer:
        server = McpServer(**kwargs)
        self.db.add(server)
        await self.db.commit()
        await self.db.refresh(server)
        return server

    async def get_server(self, server_id: uuid.UUID) -> McpServer | None:
        return await self.db.get(McpServer, server_id)

    async def list_servers(self, user_id: str) -> list[McpServer]:
        result = await self.db.execute(select(McpServer).where(McpServer.user_id == user_id))
        return list(result.scalars().all())

    async def update_server(self, server: McpServer, **kwargs) -> McpServer:
        for key, value in kwargs.items():
            setattr(server, key, value)
        await self.db.commit()
        await self.db.refresh(server)
        return server

    async def delete_server(self, server: McpServer) -> None:
        await self.db.delete(server)
        await self.db.commit()

    async def replace_tools(self, server_id: uuid.UUID, tool_specs: list[dict]) -> list[McpTool]:
        """Called after test-connection: upserts discovered tools, preserving existing approval decisions."""
        existing = await self.db.execute(select(McpTool).where(McpTool.mcp_server_id == server_id))
        existing_by_name = {t.tool_name: t for t in existing.scalars().all()}

        result_tools = []
        seen_names = set()
        for spec in tool_specs:
            seen_names.add(spec["tool_name"])
            if spec["tool_name"] in existing_by_name:
                tool = existing_by_name[spec["tool_name"]]
                tool.description = spec.get("description")
                tool.input_schema = spec.get("input_schema", {})
            else:
                tool = McpTool(mcp_server_id=server_id, **spec)
                self.db.add(tool)
            result_tools.append(tool)

        # remove tools no longer present on the server
        for name, tool in existing_by_name.items():
            if name not in seen_names:
                await self.db.delete(tool)

        await self.db.commit()
        for tool in result_tools:
            await self.db.refresh(tool)
        return result_tools

    async def get_tool(self, tool_id: uuid.UUID) -> McpTool | None:
        return await self.db.get(McpTool, tool_id)

    async def list_tools(self, server_id: uuid.UUID) -> list[McpTool]:
        result = await self.db.execute(select(McpTool).where(McpTool.mcp_server_id == server_id))
        return list(result.scalars().all())

    async def update_tool(self, tool: McpTool, **kwargs) -> McpTool:
        for key, value in kwargs.items():
            setattr(tool, key, value)
        await self.db.commit()
        await self.db.refresh(tool)
        return tool
