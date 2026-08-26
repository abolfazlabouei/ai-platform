"""Request/response schemas for /jobs."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class JobOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    stage: str
    error: str | None
    created_at: datetime
    updated_at: datetime
