"""Async CRUD queries for KBSource (the link between a KnowledgeBase and a file)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb_source import KBSource


class KBSourceRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, knowledge_base_id: uuid.UUID, file_id: uuid.UUID) -> KBSource:
        result = await self.db.execute(
            select(KBSource).where(
                KBSource.knowledge_base_id == knowledge_base_id, KBSource.file_id == file_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        kb_source = KBSource(knowledge_base_id=knowledge_base_id, file_id=file_id)
        self.db.add(kb_source)
        await self.db.commit()
        await self.db.refresh(kb_source)
        return kb_source

    async def get(self, kb_source_id: uuid.UUID) -> KBSource | None:
        return await self.db.get(KBSource, kb_source_id)

    async def list_for_kb(self, knowledge_base_id: uuid.UUID) -> list[KBSource]:
        result = await self.db.execute(select(KBSource).where(KBSource.knowledge_base_id == knowledge_base_id))
        return list(result.scalars().all())
