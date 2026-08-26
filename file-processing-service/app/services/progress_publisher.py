"""
progress_publisher: publishes {stage, percent, message} events to the Redis
channel `job:{job_id}` from inside Celery tasks (sync API), and exposes an async
generator that subscribes to that same channel for the API layer's SSE endpoint
to forward to the client (GET /jobs/{id}/stream).

Using Redis pub/sub (rather than e.g. an in-process queue) is what lets this
support ~100 concurrent uploading users: the publishing side (Celery workers,
potentially many processes/machines) and the subscribing side (FastAPI request
handlers, potentially many instances behind a load balancer) don't need to share
memory or even run on the same host.
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
    """Called from Celery tasks (sync context)."""
    client = _get_sync_redis()
    payload = json.dumps({"stage": stage, "percent": percent, "message": message})
    client.publish(job_channel(job_id), payload)


async def subscribe_progress(job_id: str) -> AsyncIterator[dict]:
    """Called from the FastAPI SSE endpoint (async context)."""
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
