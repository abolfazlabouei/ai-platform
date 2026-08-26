"""Async CRUD queries for Job."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


class JobRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Job:
        job = Job(**kwargs)
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self.db.get(Job, job_id)

    async def get_latest_for_file(self, file_id: uuid.UUID) -> Job | None:
        result = await self.db.execute(
            select(Job).where(Job.file_id == file_id).order_by(Job.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()
