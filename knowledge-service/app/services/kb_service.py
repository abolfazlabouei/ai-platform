"""
kb_service: business logic for KnowledgeBase CRUD (including Qdrant collection
lifecycle) and ingest orchestration (creating a KBSource + Job, enqueuing the
embed_kb_source Celery task per file).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStage
from app.models.kb_source import KBSource
from app.models.knowledge_base import KnowledgeBase
from app.repositories.job_repo import JobRepo
from app.repositories.kb_repo import KnowledgeBaseRepo
from app.repositories.kb_source_repo import KBSourceRepo
from app.services.vector_store import delete_collection


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.kb_repo = KnowledgeBaseRepo(db)
        self.source_repo = KBSourceRepo(db)
        self.job_repo = JobRepo(db)

    async def create(self, user_id: str, name: str, description: str | None = None) -> KnowledgeBase:
        # The Qdrant collection itself is created lazily on first ingest
        # (see vector_store.ensure_collection_sync), not here — an empty KB with
        # no sources yet doesn't need a collection.
        return await self.kb_repo.create(user_id=user_id, name=name, description=description)

    async def get(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        return await self.kb_repo.get(kb_id)

    async def list_for_user(self, user_id: str) -> list[KnowledgeBase]:
        return await self.kb_repo.list_for_user(user_id)

    async def update(self, kb: KnowledgeBase, **fields) -> KnowledgeBase:
        return await self.kb_repo.update(kb, **fields)

    async def delete(self, kb: KnowledgeBase) -> None:
        await delete_collection(str(kb.id))
        await self.kb_repo.delete(kb)  # cascades to KBSource rows via FK ondelete

    async def list_sources(self, kb_id: uuid.UUID) -> list[KBSource]:
        return await self.source_repo.list_for_kb(kb_id)

    async def ingest_file(self, kb_id: uuid.UUID, file_id: uuid.UUID) -> tuple[KBSource, Job]:
        kb_source = await self.source_repo.get_or_create(kb_id, file_id)
        job = await self.job_repo.create(kb_source_id=kb_source.id, stage=JobStage.QUEUED)

        # Imported lazily so importing kb_service never requires a broker connection.
        from app.workers.embed_tasks import embed_kb_source

        embed_kb_source.delay(str(kb_source.id), str(job.id))
        return kb_source, job
