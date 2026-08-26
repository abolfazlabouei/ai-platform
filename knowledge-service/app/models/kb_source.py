"""
KBSource ORM model: links a KnowledgeBase to a single file_id (owned by
file-processing-service) plus the ingestion status for that specific link.
A file can be linked into multiple knowledge bases; each link tracks its own
embedding progress/status independently.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class IngestStatus(str, enum.Enum):
    PENDING = "pending"
    EMBEDDING = "embedding"
    DONE = "done"
    FAILED = "failed"


class KBSource(Base):
    __tablename__ = "kb_sources"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "file_id", name="uq_kb_file"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)

    status: Mapped[IngestStatus] = mapped_column(
        Enum(IngestStatus, name="ingest_status"), default=IngestStatus.PENDING, nullable=False
    )
    chunks_embedded: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="sources")
