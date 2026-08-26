"""
LangGraph checkpointer setup, keyed by thread_id = conversation_id (as a string).
Falls back to an in-memory saver when USE_POSTGRES_CHECKPOINTER=False (dev only —
HITL resume and durability across process restarts will NOT work in that mode).
"""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import settings

_checkpointer: BaseCheckpointSaver | None = None
_ctx_manager = None


async def get_checkpointer() -> BaseCheckpointSaver:
    global _checkpointer, _ctx_manager

    if _checkpointer is not None:
        return _checkpointer

    if not settings.USE_POSTGRES_CHECKPOINTER:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        return _checkpointer

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # AsyncPostgresSaver.from_conn_string returns an async context manager;
    # we enter it once at startup and keep it open for the process lifetime.
    conn_string = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    _ctx_manager = AsyncPostgresSaver.from_conn_string(conn_string)
    _checkpointer = await _ctx_manager.__aenter__()
    await _checkpointer.setup()  # creates checkpoint tables if they don't exist
    return _checkpointer


async def close_checkpointer() -> None:
    global _ctx_manager, _checkpointer
    if _ctx_manager is not None:
        await _ctx_manager.__aexit__(None, None, None)
        _ctx_manager = None
        _checkpointer = None
