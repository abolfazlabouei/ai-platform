"""
Job status + live progress streaming. GET /jobs/{id}/stream subscribes to the Redis
channel `job:{job_id}` (populated by Celery task progress publishes) and forwards
each event as SSE, so the frontend can show "extracting... 50%" style progress
without polling — while the actual Celery worker pool scales independently.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.session import get_db
from app.repositories.job_repo import JobRepo
from app.schemas.job import JobOut
from app.services.progress_publisher import subscribe_progress

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_job_out(j) -> JobOut:
    return JobOut(id=j.id, file_id=j.file_id, stage=j.stage.value, error=j.error, created_at=j.created_at, updated_at=j.updated_at)


@router.get("/{job_id}/status", response_model=JobOut)
async def get_job_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = JobRepo(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _to_job_out(job)


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
        # Already terminal — return a single immediate event instead of hanging on a
        # subscribe that will never receive anything (the publish already happened).
        async def _immediate():
            yield f"event: progress\ndata: {json.dumps({'stage': job.stage.value, 'percent': 100, 'message': job.error or ''})}\n\n"

        return StreamingResponse(_immediate(), media_type="text/event-stream")

    return StreamingResponse(_sse_from_progress(str(job_id)), media_type="text/event-stream")
