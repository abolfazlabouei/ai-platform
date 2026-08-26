"""Async CRUD queries for File."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File


class FileRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> File:
        file_row = File(**kwargs)
        self.db.add(file_row)
        await self.db.commit()
        await self.db.refresh(file_row)
        return file_row

    async def get(self, file_id: uuid.UUID) -> File | None:
        return await self.db.get(File, file_id)

    async def list_for_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[File]:
        result = await self.db.execute(
            select(File)
            .where(File.user_id == user_id)
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def delete(self, file_row: File) -> None:
        await self.db.delete(file_row)
        await self.db.commit()
