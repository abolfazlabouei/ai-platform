"""
POST /search — embeds the query, searches across the given knowledge bases'
Qdrant collections, and returns merged top-k results. This is the exact endpoint
chat-agent-service's knowledge_retrieval graph node calls.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services.embedding_service import embed_query
from app.services.vector_store import search as vector_search

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest):
    if not body.kb_ids:
        return SearchResponse(results=[])

    query_vector = await embed_query(body.query)
    results = await vector_search(kb_ids=body.kb_ids, query_vector=query_vector, top_k=body.top_k)
    return SearchResponse(results=[SearchResultItem(**r) for r in results])
