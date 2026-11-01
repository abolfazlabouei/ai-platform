"""
Reaper: background loop that terminates idle / expired sessions, plus startup
reconciliation that removes orphan containers (e.g. left behind by a crash).

The DB row is the source of truth: a container labeled ai-platform.sandbox=1 that
is neither an active session's container nor a registered warm-pool entry is an
orphan and gets removed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import Settings, settings as default_settings
from app.db.session import AsyncSessionLocal
from app.repositories.session_repo import SessionRepo
from app.sandbox.docker_backend import DockerBackend
from app.sandbox.warm_pool import WarmPool
from app.services.session_service import SessionService

log = logging.getLogger(__name__)


def expiry_reason(created_at: datetime, last_used_at: datetime, now: datetime, cfg: Settings) -> str | None:
    if now - created_at > timedelta(seconds=cfg.SANDBOX_MAX_LIFETIME_SECONDS):
        return "max_lifetime"
    if now - last_used_at > timedelta(seconds=cfg.SANDBOX_IDLE_TTL_SECONDS):
        return "idle"
    return None


async def reap_once(backend: DockerBackend, pool: WarmPool, cfg: Settings | None = None) -> int:
    cfg = cfg or default_settings
    reaped = 0
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        service = SessionService(db, backend, pool, cfg)
        for row in await SessionRepo(db).list_active():
            reason = expiry_reason(row.created_at, row.last_used_at, now, cfg)
            if reason:
                await service.terminate(row, reason)
                reaped += 1
    return reaped


async def reconcile(backend: DockerBackend, pool: WarmPool, images: list[str]) -> None:
    """Startup: drop the (possibly stale) warm pool, remove orphans, close sessions without a container."""
    for image in images:
        await pool.drain(image)

    async with AsyncSessionLocal() as db:
        repo = SessionRepo(db)
        active = await repo.list_active()
        containers = await asyncio.to_thread(backend.list_sandbox_containers)
        running_ids = {c.id for c in containers if c.running}
        known = {row.container_id for row in active if row.container_id}

        for c in containers:
            if c.id not in known:
                log.info("reconcile: removing orphan sandbox container %s", c.id[:12])
                await asyncio.to_thread(backend.remove, c.id)

        for row in active:
            if not row.container_id or row.container_id not in running_ids:
                if row.container_id:
                    await asyncio.to_thread(backend.remove, row.container_id)
                await repo.mark_terminated(row, "container_gone")
        await repo.commit()

    for image in images:
        await pool.refill(image)


async def run_reaper(backend: DockerBackend, pool: WarmPool, cfg: Settings | None = None) -> None:
    cfg = cfg or default_settings
    while True:
        await asyncio.sleep(cfg.SANDBOX_REAPER_INTERVAL_SECONDS)
        try:
            reaped = await reap_once(backend, pool, cfg)
            if reaped:
                log.info("reaper: terminated %d session(s)", reaped)
        except Exception:  # noqa: BLE001 — keep the loop alive
            log.exception("reaper iteration failed")
