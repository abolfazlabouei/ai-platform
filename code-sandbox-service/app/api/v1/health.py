"""Liveness/readiness probes. Ready = Docker reachable + runtime registered + warm pool >= 1."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.runtime import get_runtime, sandbox_images

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    rt = get_runtime()
    checks = {
        "docker": await asyncio.to_thread(rt.backend.ping),
        "runtime": await asyncio.to_thread(rt.backend.runtime_available, settings.SANDBOX_RUNTIME),
    }
    if settings.SANDBOX_WARM_POOL_SIZE > 0:
        checks["warm_pool"] = all([await rt.pool.size(image) >= 1 for image in sandbox_images()])
    ok = all(checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)
