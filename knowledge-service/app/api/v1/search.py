"""
POST /search — hybrid retrieval. Embeds the query and runs it against both the
dense (Qdrant) and lexical (Postgres full-text) retrievers for the given knowledge
bases, fuses the two ranked lists with Reciprocal Rank Fusion, optionally reranks
the fused window, and returns the top-k. This is the exact endpoint
chat-agent-service's knowledge_retrieval graph node calls (response shape unchanged;
`debug` is only populated when the request sets debug=true).

Fusion key is f"{knowledge_base_id}:{chunk_id}" rather than bare chunk_id: the same
file (and so the same chunk_ids) can be linked into more than one knowledge base,
and a multi-KB search should keep those as distinct hits.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.repositories.kb_chunk_repo import KBChunkRepo
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services import reranker
from app.services.embedding_service import embed_query
from app.services.fusion import reciprocal_rank_fusion
from app.services.text_normalize import normalize_text, query_terms
from app.services.vector_store import search as dense_search

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)


def _key(hit: dict) -> str:
    return f"{hit['knowledge_base_id']}:{hit['chunk_id']}"


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, db: AsyncSession = Depends(get_db)):
    if not body.kb_ids:
        return SearchResponse(results=[])

    query_vector = await embed_query(normalize_text(body.query))

    if not settings.HYBRID_SEARCH_ENABLED:
        results = await dense_search(kb_ids=body.kb_ids, query_vector=query_vector, top_k=body.top_k)
        return SearchResponse(results=[SearchResultItem(**r) for r in results])

    dense_hits, lexical_hits = await asyncio.gather(
        dense_search(kb_ids=body.kb_ids, query_vector=query_vector, top_k=settings.DENSE_TOP_K),
        KBChunkRepo(db).lexical_search(kb_ids=body.kb_ids, query=body.query, top_k=settings.LEXICAL_TOP_K),
    )

    # dense hits carry full metadata, so they win when both retrievers return a chunk
    hits_by_key = {_key(h): h for h in [*lexical_hits, *dense_hits]}
    fused = reciprocal_rank_fusion(
        [[_key(h) for h in dense_hits], [_key(h) for h in lexical_hits]],
        k=settings.RRF_K,
        weights=[settings.RRF_DENSE_WEIGHT, settings.RRF_LEXICAL_WEIGHT],
    )
    candidates = [{**hits_by_key[key], "score": score} for key, score in fused[: settings.RERANK_CANDIDATE_K]]

    rerank_fallback = False
    if settings.ENABLE_RERANK and candidates:
        try:
            results = await reranker.rerank(body.query, candidates, top_k=body.top_k)
        except Exception:  # noqa: BLE001
            logger.exception("Reranker failed; falling back to fused results.")
            rerank_fallback = True
            results = candidates[: body.top_k]
    else:
        results = candidates[: body.top_k]

    debug = None
    if body.debug:

        def brief(hits: list[dict]) -> list[dict]:
            return [
                {"chunk_id": h["chunk_id"], "score": round(h["score"], 5), "preview": (h["content"] or "")[:150]}
                for h in hits[:10]
            ]

        debug = {
            "lexical_terms": query_terms(body.query),
            "rerank_enabled": settings.ENABLE_RERANK,
            "rerank_fallback": rerank_fallback,
            "dense_top": brief(dense_hits),
            "lexical_top": brief(lexical_hits),
            "fused_top": brief(candidates),
        }

    return SearchResponse(results=[SearchResultItem(**r) for r in results], debug=debug)
