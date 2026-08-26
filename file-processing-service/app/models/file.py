"""
File ORM model: metadata for an uploaded raw file. The binary content itself lives
in object storage under `storage_key`; this row tracks lifecycle status so the API
and knowledge-service ingestion can reason about whether a file is ready to use.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class FileStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    DONE = "done"
    FAILED = "failed"


class FileType(str, enum.Enum):
    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_type: Mapped[FileType] = mapped_column(Enum(FileType, name="file_type"), default=FileType.UNKNOWN)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status"), default=FileStatus.UPLOADED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="file", cascade="all, delete-orphan")
