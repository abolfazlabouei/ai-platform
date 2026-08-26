"""
Shared async Redis client. Roles:
  1. Celery broker/result backend for embed_tasks (configured in workers/celery_app.py).
  2. Pub/Sub channel `job:{job_id}` for ingest progress — same pattern as
     file-processing-service, so the frontend can show one consistent progress UX
     regardless of which service is doing the work.
"""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def job_channel(job_id: str) -> str:
    return f"job:{job_id}"
