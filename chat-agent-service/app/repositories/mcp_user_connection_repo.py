"""Async CRUD queries for McpUserConnection."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_user_connection import McpUserConnection


class McpUserConnectionRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, mcp_server_id: uuid.UUID, user_id: str) -> McpUserConnection | None:
        stmt = select(McpUserConnection).where(
            McpUserConnection.mcp_server_id == mcp_server_id,
            McpUserConnection.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def upsert(self, mcp_server_id: uuid.UUID, user_id: str, **fields: Any) -> McpUserConnection:
        connection = await self.get(mcp_server_id, user_id)
        if connection is not None:
            for key, value in fields.items():
                setattr(connection, key, value)
            await self.db.commit()
            await self.db.refresh(connection)
            return connection

        connection = McpUserConnection(mcp_server_id=mcp_server_id, user_id=user_id, **fields)
        self.db.add(connection)
        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    async def delete(self, connection: McpUserConnection) -> None:
        await self.db.delete(connection)
        await self.db.commit()
