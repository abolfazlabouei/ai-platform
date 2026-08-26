"""
FastAPI application entrypoint for file-processing-service.

This process only handles HTTP (upload, status, SSE progress, chunk retrieval) —
the actual extraction/chunking work happens in separate Celery worker processes
(see app/workers/celery_app.py), so this app stays responsive under many
concurrent uploads/SSE-watchers even while workers are busy on CPU-heavy files.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import files, health, jobs
from app.core.redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic (see app/db/migrations) — run `alembic upgrade
    # head` before starting the service.
    get_redis()
    yield
    await close_redis()


app = FastAPI(
    title="file-processing-service",
    description="Uploads, extracts (docx/pdf/xlsx/markdown, including tables and "
    "embedded images), and chunks documents. Processing runs asynchronously via "
    "Celery with live progress pushed over Redis pub/sub + SSE.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(health.router)
app.include_router(files.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
