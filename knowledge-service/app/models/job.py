"""
Job ORM model: tracks a single ingest run (one KBSource being embedded), so
GET /jobs/{id}/stream (mirroring file-processing-service's API shape) can report
progress consistently across both services.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class JobStage(str, enum.Enum):
    QUEUED = "queued"
    EMBEDDING = "embedding"
    DONE = "done"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_sources.id", ondelete="CASCADE"), index=True, nullable=False
    )

    stage: Mapped[JobStage] = mapped_column(Enum(JobStage, name="job_stage"), default=JobStage.QUEUED)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
