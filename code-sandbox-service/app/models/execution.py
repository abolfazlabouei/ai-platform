"""
SandboxExecution: audit row for every code run. The code is stored in full — this
table is the audit trail for what LLM-written code actually executed.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SandboxExecution(Base):
    __tablename__ = "sandbox_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oom_killed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stdout_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stderr_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_keys: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
