"""Request/response schemas for /search — consumed directly by chat-agent-service's
knowledge_retrieval graph node."""
from __future__ import annotations

from pydantic import BaseModel


class SearchRequest(BaseModel):
    kb_ids: list[str]
    query: str
    top_k: int = 6


class SearchResultItem(BaseModel):
    score: float
    chunk_id: str | None
    file_id: str | None
    knowledge_base_id: str
    content: str | None
    type: str | None
    metadata: dict = {}


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
