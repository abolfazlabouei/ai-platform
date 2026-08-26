"""
Job ORM model — tracks the async processing pipeline for a single file
(extracting -> chunking -> done/failed). Progress WITHIN a stage is not persisted
here (that's transient, pushed only through Redis pub/sub for live SSE watchers);
this table is the durable record of which stage a file reached and any terminal error.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class JobStage(str, enum.Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    DONE = "done"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), index=True, nullable=False
    )

    stage: Mapped[JobStage] = mapped_column(Enum(JobStage, name="job_stage"), default=JobStage.QUEUED)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    file: Mapped["File"] = relationship(back_populates="jobs")
