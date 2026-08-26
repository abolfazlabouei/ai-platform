"""Async CRUD queries for Job."""
from __future__ import annotations

import uuid

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
