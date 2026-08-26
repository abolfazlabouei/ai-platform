"""Async CRUD queries for Chunk. Read-heavy — this is what knowledge-service pulls from."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk


class ChunkRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_file(self, file_id: uuid.UUID) -> list[Chunk]:
        result = await self.db.execute(
            select(Chunk).where(Chunk.file_id == file_id).order_by(Chunk.order_index)
        )
        return list(result.scalars().all())

    async def list_for_files(self, file_ids: list[uuid.UUID]) -> list[Chunk]:
        result = await self.db.execute(
            select(Chunk).where(Chunk.file_id.in_(file_ids)).order_by(Chunk.file_id, Chunk.order_index)
        )
        return list(result.scalars().all())
