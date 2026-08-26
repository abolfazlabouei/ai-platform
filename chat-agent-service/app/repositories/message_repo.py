"""Async CRUD queries for Message."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


class MessageRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, **kwargs) -> Message:
        msg = Message(**kwargs)
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def list_for_conversation(self, conversation_id: uuid.UUID, limit: int = 50) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))
