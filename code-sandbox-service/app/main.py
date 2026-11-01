"""
FastAPI application entrypoint for code-sandbox-service — the control plane for
isolated code execution. It is the ONLY component with access to the Docker socket,
and is reachable only from inside the platform (no published host port).

Lifespan: Docker backend + warm pool, startup reconciliation (orphan containers,
stale sessions), the reaper loop, and the MCP session manager.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1 import executions, files, health, sessions
from app.core.redis_client import close_redis
from app.mcp_server.server import build_mcp_app, mcp_lifespan
from app.sandbox.executor import ExecutionError
from app.sandbox.files import PathError
from app.sandbox.reaper import reconcile, run_reaper
from app.services.execution_service import RateLimited, SessionBusy
from app.services.runtime import init_runtime, sandbox_images
from app.services.session_service import CapacityError, SessionNotFound

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic (entrypoint.sh runs `alembic upgrade head`).
    rt = init_runtime()
    try:
        await reconcile(rt.backend, rt.pool, sandbox_images())
    except Exception:  # noqa: BLE001 — start anyway; /ready reports the problem
        log.exception("startup reconciliation failed")
    reaper = asyncio.create_task(run_reaper(rt.backend, rt.pool))
    async with mcp_lifespan():
        yield
    reaper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reaper
    await close_redis()


app = FastAPI(
    title="code-sandbox-service",
    description="Isolated code execution for agents: per-conversation gVisor sandboxes, "
    "exposed as REST (/api/v1) and as an MCP server (/mcp).",
    version="0.1.0",
    lifespan=lifespan,
)


_STATUS = {
    ExecutionError: 400,
    PathError: 400,
    SessionNotFound: 404,
    SessionBusy: 409,
    CapacityError: 429,
    RateLimited: 429,
}


for _exc, _code in _STATUS.items():

    def _make(code: int):
        async def handler(_: Request, exc: Exception):
            return JSONResponse({"detail": str(exc)}, status_code=code)

        return handler

    app.add_exception_handler(_exc, _make(_code))


API_PREFIX = "/api/v1"
app.include_router(health.router)
app.include_router(sessions.router, prefix=API_PREFIX)
app.include_router(executions.router, prefix=API_PREFIX)
app.include_router(files.router, prefix=API_PREFIX)
# Must stay last: catches /mcp after every FastAPI route had its chance.
app.mount("/", build_mcp_app())
