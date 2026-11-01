"""
WarmPool: keeps SANDBOX_WARM_POOL_SIZE started, empty containers per image so the
first exec of a new session does not pay gVisor's container start latency.

Pool containers are created with the exact same spec as session containers
(spec.build_container_kwargs) and never hold user data. Claiming is an atomic
Redis LPOP; the claimed container is checked to still be running before use.
Docker labels are immutable, so a claimed container keeps `ai-platform.sandbox.pool=1`;
reconciliation treats the DB row (session.container_id) as the source of truth.
"""
from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis

from app.core.config import Settings, settings as default_settings
from app.core.redis_client import pool_key
from app.sandbox.docker_backend import DockerBackend
from app.sandbox.spec import build_container_kwargs

log = logging.getLogger(__name__)


class WarmPool:
    def __init__(self, backend: DockerBackend, redis_client: redis.Redis, cfg: Settings | None = None):
        self.backend = backend
        self.redis = redis_client
        self.cfg = cfg or default_settings
        self._refill_lock = asyncio.Lock()

    async def create_container(self, image: str, session_id: str | None) -> str:
        kwargs = build_container_kwargs(image, session_id=session_id, cfg=self.cfg)
        return await asyncio.to_thread(self.backend.create_and_start, kwargs)

    async def claim(self, image: str) -> str | None:
        """Pops a running pool container, or None if the pool is empty."""
        while True:
            container_id = await self.redis.lpop(pool_key(image))
            if container_id is None:
                return None
            state = await asyncio.to_thread(self.backend.state, container_id)
            if state and state.get("Running"):
                return container_id
            await asyncio.to_thread(self.backend.remove, container_id)  # stale entry

    async def size(self, image: str) -> int:
        return int(await self.redis.llen(pool_key(image)))

    async def refill(self, image: str) -> None:
        if self.cfg.SANDBOX_WARM_POOL_SIZE <= 0:
            return
        async with self._refill_lock:
            missing = self.cfg.SANDBOX_WARM_POOL_SIZE - await self.size(image)
            for _ in range(max(0, missing)):
                try:
                    container_id = await self.create_container(image, session_id=None)
                except Exception:  # noqa: BLE001 — pool is best-effort; sessions create on demand
                    log.exception("warm pool: failed to create container for %s", image)
                    return
                await self.redis.rpush(pool_key(image), container_id)

    def refill_in_background(self, image: str) -> None:
        asyncio.get_running_loop().create_task(self.refill(image))

    async def registered_ids(self, image: str) -> set[str]:
        return set(await self.redis.lrange(pool_key(image), 0, -1))

    async def drain(self, image: str) -> None:
        """Removes every pool container (used on startup before re-warming)."""
        while (container_id := await self.redis.lpop(pool_key(image))) is not None:
            await asyncio.to_thread(self.backend.remove, container_id)
