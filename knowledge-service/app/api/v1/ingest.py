"""
POST /knowledge-bases/{id}/ingest {file_ids: [...]} — links each file into the
knowledge base (creating/reusing a KBSource) and enqueues one embed_kb_source
Celery task per file. Progress for each is watchable via GET /jobs/{job_id}/stream
(same SSE pattern as file-processing-service).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.ingest import IngestJobOut, IngestRequest, IngestResponse
from app.services.kb_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["ingest"])


@router.post("/{kb_id}/ingest", response_model=IngestResponse)
async def ingest_files(kb_id: uuid.UUID, body: IngestRequest, db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    kb = await service.get(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    jobs = []
    for file_id in body.file_ids:
        kb_source, job = await service.ingest_file(kb_id, file_id)
        jobs.append(IngestJobOut(file_id=file_id, kb_source_id=kb_source.id, job_id=job.id))

    return IngestResponse(jobs=jobs)
