"""
reranker: optional re-ranking of the fused (dense + lexical) candidates.

Two backends (settings.RERANK_BACKEND):
  - "openrouter_api": hosted rerank endpoint, needs only RERANK_API_KEY (no torch).
  - "local": sentence-transformers CrossEncoder, loaded once and lazily. Requires
    `pip install sentence-transformers` and a MULTILINGUAL model for Persian
    (English-only models such as ms-marco-MiniLM rank Persian text poorly).

Feature-flagged via ENABLE_RERANK (off by default): it runs inline in every RAG
chat turn, so it adds latency. search.py falls back to the fused order on any error.
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None  # lazily-loaded CrossEncoder (local backend)


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The local reranker requires sentence-transformers "
                "(pip install sentence-transformers) or set RERANK_BACKEND=openrouter_api."
            ) from exc
        _model = CrossEncoder(settings.RERANK_MODEL)
    return _model


def warm_up() -> None:
    """Best-effort eager model load at startup. Never raises: a broken reranker
    must not stop the service — search.py already falls back per request."""
    try:
        if settings.RERANK_BACKEND == "local":
            _get_model()
        elif not settings.RERANK_API_KEY:
            logger.warning("ENABLE_RERANK is on but RERANK_API_KEY is not set; reranking will fall back.")
    except Exception:  # noqa: BLE001
        logger.exception("Reranker warm-up failed; searches will fall back to fused order.")


def rerank_sync(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates or top_k <= 0:
        return []
    model = _get_model()
    pairs = [(query, c.get("content") or "") for c in candidates]
    scores = model.predict(pairs, batch_size=settings.RERANK_BATCH_SIZE, show_progress_bar=False)
    reranked = [{**c, "score": float(s)} for c, s in zip(candidates, scores)]
    reranked.sort(key=lambda hit: -hit["score"])
    return reranked[:top_k]


async def _rerank_openrouter(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not settings.RERANK_API_KEY:
        raise RuntimeError("RERANK_API_KEY is not configured.")

    payload = {
        "model": settings.RERANK_API_MODEL,
        "query": query,
        "documents": [c.get("content") or "" for c in candidates],
        "top_n": min(top_k, len(candidates)),
    }
    async with httpx.AsyncClient(timeout=settings.RERANK_API_TIMEOUT_SECONDS) as client:
        response = await client.post(
            settings.RERANK_API_URL,
            headers={"Authorization": f"Bearer {settings.RERANK_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.is_error:
        raise RuntimeError(f"Rerank API failed: HTTP {response.status_code}; {response.text[:500]}")

    results = []
    for item in response.json().get("results", []):
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            raise RuntimeError("Rerank API returned an invalid document index.")
        score = float(item["relevance_score"])
        results.append({**candidates[index], "score": score})
    results.sort(key=lambda hit: -hit["score"])
    return results[:top_k]


async def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates or top_k <= 0:
        return []
    if settings.RERANK_BACKEND == "openrouter_api":
        return await _rerank_openrouter(query, candidates, top_k)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(rerank_sync, query, candidates, top_k))
