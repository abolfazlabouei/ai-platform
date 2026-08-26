"""
progress_publisher: publishes {stage, percent, message} events to Redis channel
`job:{job_id}` from Celery tasks (sync), and exposes an async subscribe generator
for the API layer's SSE endpoint. Identical pattern to file-processing-service, so
the frontend's progress-watching code can be shared/reused across both services.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import redis as sync_redis

from app.core.config import settings
from app.core.redis_client import get_redis, job_channel

_sync_redis_client: sync_redis.Redis | None = None


def _get_sync_redis() -> sync_redis.Redis:
    global _sync_redis_client
    if _sync_redis_client is None:
        _sync_redis_client = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _sync_redis_client


def publish_progress_sync(job_id: str, stage: str, percent: int, message: str = "") -> None:
    client = _get_sync_redis()
    payload = json.dumps({"stage": stage, "percent": percent, "message": message})
    client.publish(job_channel(job_id), payload)


async def subscribe_progress(job_id: str) -> AsyncIterator[dict]:
    redis_client = get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(job_channel(job_id))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            yield data
            if data.get("stage") in ("done", "failed"):
                break
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.aclose()
