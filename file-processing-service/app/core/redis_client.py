"""
Shared async Redis client. Two roles here:
  1. Celery broker/result backend (configured separately in workers/celery_app.py).
  2. Pub/Sub channel `job:{job_id}` used to push extraction/chunking progress from
     Celery workers to the API layer, which forwards it to the client via SSE.
     This is what lets the HTTP layer stay decoupled from and non-blocking on the
     (potentially slow) Celery task, while still supporting ~100 concurrent
     upload+progress-watching clients.
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
