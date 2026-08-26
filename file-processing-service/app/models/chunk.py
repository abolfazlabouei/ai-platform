"""
Chunk ORM model — the output of extraction+chunking. Shape mirrors
shared_schemas.chunk.Chunk exactly (see chunk_repo.to_shared_schema) so
knowledge-service can consume it over HTTP with zero translation ambiguity.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ChunkType(str, enum.Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), index=True, nullable=False
    )

    type: Mapped[ChunkType] = mapped_column(Enum(ChunkType, name="chunk_type"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # text, markdown-table, or image caption
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # set for type == IMAGE
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    file: Mapped["File"] = relationship(back_populates="chunks")
