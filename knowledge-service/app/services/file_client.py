"""
Typed HTTP client to file-processing-service. Two entrypoints: async (used by the
/ingest endpoint to kick off a Celery task) and sync (used INSIDE embed_tasks.py,
which runs outside the asyncio event loop).
"""
from __future__ import annotations

import httpx

from app.core.config import settings


async def get_chunks(file_id: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.FILE_SERVICE_URL, timeout=120) as client:
        resp = await client.get(f"/api/v1/files/{file_id}/chunks")
        resp.raise_for_status()
        return resp.json()


def get_chunks_sync(file_id: str) -> list[dict]:
    with httpx.Client(base_url=settings.FILE_SERVICE_URL, timeout=120) as client:
        resp = client.get(f"/api/v1/files/{file_id}/chunks")
        resp.raise_for_status()
        return resp.json()
