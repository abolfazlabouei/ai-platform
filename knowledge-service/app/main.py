"""
FastAPI entrypoint for knowledge-service.

Like file-processing-service, the HTTP layer only handles CRUD + kicking off
Celery embed jobs + serving /search (which itself is a fast embed-query +
Qdrant-search, not heavy enough to need a background task). Actual bulk embedding
happens in separate Celery workers (app/workers/celery_app.py).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import ingest, jobs, knowledge_bases, search, health
from app.core.redis_client import close_redis, get_redis
from app.core.config import settings
from app.services import reranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic (see app/db/migrations) — run `alembic upgrade
    # head` before starting the service.
    get_redis()
    if settings.ENABLE_RERANK:
        reranker.warm_up()
    yield
    await close_redis()


app = FastAPI(
    title="knowledge-service",
    description="Knowledge base CRUD, ingest (embeds chunks pulled from "
    "file-processing-service into a per-KB Qdrant collection), and vector search "
    "consumed by chat-agent-service's knowledge_retrieval graph node.",
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
app.include_router(knowledge_bases.router, prefix=API_PREFIX)
app.include_router(ingest.router, prefix=API_PREFIX)
app.include_router(search.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
