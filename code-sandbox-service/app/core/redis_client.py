"""
Shared async Redis client. Used for:
  - the per-session execution lock  (sandbox:lock:<session_id>)
  - the warm-pool registry          (sandbox:pool:<image>)
  - per-user abuse limits           (sandbox:rate:<user_id>:<minute>, sandbox:cpu:<user_id>:<day>)
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


def lock_key(session_id: str) -> str:
    return f"sandbox:lock:{session_id}"


def pool_key(image: str) -> str:
    return f"sandbox:pool:{image}"
