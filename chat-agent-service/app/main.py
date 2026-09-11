"""
FastAPI application entrypoint for chat-agent-service.

Mounts all v1 routers, manages startup/shutdown of shared resources (DB engine,
Redis client, LangGraph checkpointer connection), and exposes /health, /ready.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    agents,
    channel_identities,
    chat,
    conversations,
    health,
    knowledge_proxy,
    mcp_oauth,
    mcp_servers,
    media,
    tool_approval,
)
from app.checkpointer.postgres_saver import close_checkpointer, get_checkpointer
from app.core.config import settings
from app.core.redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    # Schema is managed by Alembic (see app/db/migrations) — run `alembic upgrade
    # head` before starting the service. This lifespan intentionally does NOT
    # auto-create tables: doing so would create them outside Alembic's tracking
    # and cause "relation already exists" the first time a real migration runs.
    await get_checkpointer()  # opens the Postgres connection used by LangGraph, once
    get_redis()

    yield
    if settings.LANGFUSE_ENABLED:
        # Langfuse's SDK batches trace data and sends it asynchronously in the
        # background; without an explicit shutdown/flush, traces from the last
        # few seconds before the process exits can be silently dropped.
        from langfuse import get_client

        get_client().shutdown()
    # --- shutdown ---
    await close_checkpointer()
    await close_redis()


app = FastAPI(
    title="chat-agent-service",
    description="LangGraph-based chat & agent runtime: streaming/complete chat, "
    "MCP tool integration with human-in-the-loop approval, knowledge base retrieval, "
    "multimodal input/output, and full Agent CRUD.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(health.router)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(agents.router, prefix=API_PREFIX)
app.include_router(conversations.router, prefix=API_PREFIX)
app.include_router(mcp_servers.router, prefix=API_PREFIX)
app.include_router(mcp_oauth.router, prefix=API_PREFIX)
app.include_router(tool_approval.router, prefix=API_PREFIX)
app.include_router(knowledge_proxy.router, prefix=API_PREFIX)
app.include_router(media.router, prefix=API_PREFIX)
app.include_router(channel_identities.router, prefix=API_PREFIX)
