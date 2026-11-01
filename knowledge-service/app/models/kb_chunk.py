"""
KBChunk ORM model: a Postgres-side copy of each embedded chunk's text, used for
lexical (keyword) search — the complement to Qdrant's dense vector search.

Populated by embed_tasks.py::embed_kb_source at the same time chunks are
upserted into Qdrant, so the two stores are populated from the same ingest
pass and stay in sync without a separate step.

content_tsv is a Postgres GENERATED ALWAYS AS ... STORED column (see the
migration that creates this table) backed by a GIN index — Postgres computes
and maintains it automatically on insert; nothing in application code needs
to set it.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KBChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "chunk_id", name="uq_kb_chunks_kb_chunk"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Postgres-managed generated column
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
