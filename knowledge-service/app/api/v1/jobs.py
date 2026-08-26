"""Job status + live progress streaming for ingest jobs — same SSE pattern as
file-processing-service's /jobs endpoint, kept consistent across both services."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.session import get_db
from app.repositories.job_repo import JobRepo
from app.services.progress_publisher import subscribe_progress

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}/status")
async def get_job_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = JobRepo(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"id": str(job.id), "kb_source_id": str(job.kb_source_id), "stage": job.stage.value, "error": job.error}


async def _sse_from_progress(job_id: str):
    async for event in subscribe_progress(job_id):
        yield f"event: progress\ndata: {json.dumps(event)}\n\n"


@router.get("/{job_id}/stream")
async def stream_job_progress(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = JobRepo(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.stage.value in ("done", "failed"):
        async def _immediate():
            yield f"event: progress\ndata: {json.dumps({'stage': job.stage.value, 'percent': 100, 'message': job.error or ''})}\n\n"

        return StreamingResponse(_immediate(), media_type="text/event-stream")

    return StreamingResponse(_sse_from_progress(str(job_id)), media_type="text/event-stream")
