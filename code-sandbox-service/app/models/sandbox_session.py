"""
SandboxSession: one isolated container per conversation, with a persistent
/workspace for the life of the session. At most one non-terminated session per
conversation_id (partial unique index). `container_id` changes on reset or when a
dead container is transparently replaced; the session id stays the same.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SessionStatus(str, enum.Enum):
    CREATING = "creating"
    READY = "ready"
    BUSY = "busy"
    TERMINATED = "terminated"
    ERROR = "error"


class SandboxSession(Base):
    __tablename__ = "sandbox_sessions"
    __table_args__ = (
        Index(
            "uq_sandbox_sessions_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status != 'TERMINATED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    image: Mapped[str] = mapped_column(String(128), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="sandbox_session_status"), default=SessionStatus.CREATING, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminate_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
