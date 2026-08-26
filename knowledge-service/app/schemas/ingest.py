"""Request/response schemas for /knowledge-bases/{id}/ingest."""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class IngestRequest(BaseModel):
    file_ids: list[uuid.UUID]


class IngestJobOut(BaseModel):
    file_id: uuid.UUID
    kb_source_id: uuid.UUID
    job_id: uuid.UUID


class IngestResponse(BaseModel):
    jobs: list[IngestJobOut]
