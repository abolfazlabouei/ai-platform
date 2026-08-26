"""
Shared async Redis client. Used for:
  - Pub/Sub notifications (e.g. forwarding job progress from file/knowledge services if ever needed here)
  - Lightweight distributed locks / rate limiting for concurrent streaming connections
Kept as a single lazily-initialized client so all modules share one connection pool.
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
