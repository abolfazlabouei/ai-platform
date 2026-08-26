"""Request/response schemas for /files."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class FileOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime: str | None
    file_type: str
    size_bytes: int
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class FileUploadResponse(BaseModel):
    file: FileOut
    job_id: uuid.UUID


class ChunkOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    type: str
    content: str
    storage_key: str | None
    order_index: int
    extra_metadata: dict
