"""Async CRUD queries for KnowledgeBase."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase


class KnowledgeBaseRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> KnowledgeBase:
        kb = KnowledgeBase(**kwargs)
        self.db.add(kb)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def get(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        return await self.db.get(KnowledgeBase, kb_id)

    async def list_for_user(self, user_id: str) -> list[KnowledgeBase]:
        result = await self.db.execute(select(KnowledgeBase).where(KnowledgeBase.user_id == user_id))
        return list(result.scalars().all())

    async def update(self, kb: KnowledgeBase, **kwargs) -> KnowledgeBase:
        for key, value in kwargs.items():
            setattr(kb, key, value)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def delete(self, kb: KnowledgeBase) -> None:
        await self.db.delete(kb)
        await self.db.commit()
