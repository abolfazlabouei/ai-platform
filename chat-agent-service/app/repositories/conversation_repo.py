"""Async CRUD queries for Conversation. No business logic here — see conversation_service.py."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation


class ConversationRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Conversation:
        conv = Conversation(**kwargs)
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self.db.get(Conversation, conversation_id)

    async def list_for_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def delete(self, conversation: Conversation) -> None:
        await self.db.delete(conversation)
        await self.db.commit()

    async def update(self, conversation: Conversation, **kwargs) -> Conversation:
        for key, value in kwargs.items():
            setattr(conversation, key, value)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation
