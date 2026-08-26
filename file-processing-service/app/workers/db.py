"""
Sync SQLAlchemy engine/session for use INSIDE Celery tasks. Celery workers run
outside the asyncio event loop that FastAPI uses, so tasks.py deliberately uses
this synchronous session rather than trying to bridge into app.db.session's
async engine. Same DATABASE_URL, different driver (psycopg2 instead of asyncpg).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, class_=Session)
