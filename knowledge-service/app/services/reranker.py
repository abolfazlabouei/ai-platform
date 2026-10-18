"""
reranker: cross-encoder re-ranking on top of the fused RRF candidates.

Cross-encoders concatenate (query, doc) and score them jointly through one
transformer pass — far more accurate than the bi-encoder cosine similarity or
lexical ts_rank scores used to build the candidate set, but too slow to run
over a full corpus. This only ever runs on the small fused candidate window
(settings.RERANK_CANDIDATE_K), never on raw retrieval results directly.

Feature-flagged via ENABLE_RERANK: this runs inline in every RAG-enabled chat
turn (knowledge_retrieval blocks llm_node), so it's a real latency cost worth
A/B-ing before committing to.

The model is loaded once, lazily, mirroring vector_store.py's `_client`
pattern — loading it per-request would be far too slow. `warm_up()` forces
that load eagerly at app startup instead of paying
the cost on whichever request happens to arrive first.
"""
from __future__ import annotations

import asyncio
from functools import partial

import httpx

from app.core.config import settings


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The local reranker requires sentence-transformers. "
                "Install it with: python -m pip install sentence-transformers"
            ) from exc

        _model = CrossEncoder(settings.RERANK_MODEL)
    return _model


def warm_up() -> None:
    """Load the local model only when using the local backend."""
    if settings.RERANK_BACKEND == "local":
        _get_model()
    elif settings.RERANK_BACKEND == "openrouter_api":
        if not settings.RERANK_API_KEY:
            raise RuntimeError("RERANK_API_KEY is not configured.")


def rerank_sync(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Rerank candidates using the local CrossEncoder."""
    if not candidates or top_k <= 0:
        return []

    model = _get_model()
    pairs = [(query, c.get("content") or "") for c in candidates]
    scores = model.predict(pairs, batch_size=settings.RERANK_BATCH_SIZE, show_progress_bar=False)

    reranked = [
        {**candidate, "score": float(score)}
        for candidate, score in zip(candidates, scores)
    ]
    reranked.sort(key=lambda hit: -hit["score"])
    return reranked[:top_k]


async def _rerank_openrouter(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not settings.RERANK_API_KEY:
        raise RuntimeError("RERANK_API_KEY is not configured.")

    documents = [candidate.get("content") or "" for candidate in candidates]

    payload = {
        "model": settings.RERANK_API_MODEL,
        "query": query,
        "documents": documents,
        "top_n": min(top_k, len(documents)),
    }

    async with httpx.AsyncClient(
        timeout=settings.RERANK_API_TIMEOUT_SECONDS
    ) as client:
        response = await client.post(
            settings.RERANK_API_URL,
            headers={
                "Authorization": f"Bearer {settings.RERANK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if response.is_error:
            raise RuntimeError(
                f"OpenRouter Rerank API failed: HTTP {response.status_code}; "
                f"{response.text[:1000]}"
            )

        data = response.json()

    results = []
    for item in data.get("results", []):
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            raise RuntimeError("Rerank API returned an invalid document index.")

        score = float(item["relevance_score"])
        results.append(
            {
                **candidates[index],
                "score": score,
                "rerank_score": score,
            }
        )

    results.sort(key=lambda hit: -hit["score"])
    return results[:top_k]


async def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Select a reranking backend without changing the search API."""
    if not candidates or top_k <= 0:
        return []

    if settings.RERANK_BACKEND == "openrouter_api":
        return await _rerank_openrouter(query, candidates, top_k)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(rerank_sync, query, candidates, top_k),)