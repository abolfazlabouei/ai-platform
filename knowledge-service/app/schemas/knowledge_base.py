"""Request/response schemas for /knowledge-bases."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class KBSourceOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    file_id: uuid.UUID
    status: str
    chunks_embedded: int
    error: str | None
