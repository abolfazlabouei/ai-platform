"""
Chunk contract produced by file-processing-service, consumed by knowledge-service.
Kept here so both services (and any future consumer) agree on the exact shape.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Chunk(BaseModel):
    id: str
    file_id: str
    type: Literal["text", "table", "image"]
    content: str  # raw text, markdown-table serialization, or an image caption
    storage_key: str | None = None  # populated for type == "image"
    order_index: int
    metadata: dict = {}
