"""
POST /search — embeds the query, runs it against both the dense (Qdrant) and
lexical (Postgres full-text) retrievers for the given knowledge bases, fuses
the two ranked lists with Reciprocal Rank Fusion, and returns the fused top-k.
This is the exact endpoint chat-agent-service's knowledge_retrieval graph node calls.

Fusion key is f"{knowledge_base_id}:{chunk_id}" rather than bare chunk_id: the
same file (and so the same chunk_ids) can be linked into more than one
knowledge base (see KBSource's docstring), and a multi-KB search should keep
those as distinct hits rather than collapsing them.
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
from app.services.vector_store import search as dense_search
from app.services.text_normalize import normalize_text, query_terms

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

def _fusion_key(hit: dict) -> str:
    return f"{hit['knowledge_base_id']}:{hit['chunk_id']}"


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, db: AsyncSession = Depends(get_db)):
    if not body.kb_ids:
        return SearchResponse(results=[])

    query_vector = await embed_query(normalize_text(body.query))
    kb_chunk_repo = KBChunkRepo(db)

    dense_hits, lexical_hits = await asyncio.gather(
        dense_search(kb_ids=body.kb_ids, query_vector=query_vector, top_k=settings.DENSE_TOP_K),
        kb_chunk_repo.lexical_search(kb_ids=body.kb_ids, query=body.query, top_k=settings.LEXICAL_TOP_K),
    )

    hits_by_key = {_fusion_key(h): h for h in dense_hits + lexical_hits}
    rankings = [
        [_fusion_key(h) for h in dense_hits],
        [_fusion_key(h) for h in lexical_hits],
    ]
    fused = reciprocal_rank_fusion(rankings, k=settings.RRF_K, weights=[settings.RRF_DENSE_WEIGHT,
        settings.RRF_LEXICAL_WEIGHT])

    candidates = []
    for key, fused_score in fused[: settings.RERANK_CANDIDATE_K]:
        hit = hits_by_key.get(key)
        if hit is None:
            continue
        candidates.append({**hit, "score": fused_score})

    rerank_fallback = False

    if settings.ENABLE_RERANK and candidates:
        try:
            results = await reranker.rerank(
                body.query,
                candidates,
                top_k=body.top_k,
            )
        except Exception:
            logger.exception("Reranker failed; falling back to fused results.")
            rerank_fallback = True
            results = candidates[: body.top_k]
    else:
        results = candidates[: body.top_k]

    debug = None
    if body.debug:
        def _brief(hits: list[dict]) -> list[dict]:
            return [
                {"chunk_id": h["chunk_id"], "score": round(h["score"], 5), "preview": (h["content"] or "")[:150]}
                for h in hits[:10]
            ]

        debug = {
            "lexical_terms": query_terms(body.query),
            "rerank_enabled": settings.ENABLE_RERANK,
            "dense_top": _brief(dense_hits),
            "lexical_top": _brief(lexical_hits),
            "fused_top": _brief(candidates),
            "dense_ids": [h["chunk_id"] for h in dense_hits],
            "lexical_ids": [h["chunk_id"] for h in lexical_hits],
            "fused_ids": [key.split(":", 1)[1] for key, _ in fused],
            "rerank_fallback": rerank_fallback,
        }

    return SearchResponse(results=[SearchResultItem(**r) for r in results], debug=debug)