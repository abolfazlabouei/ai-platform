"""
Provider-agnostic embedding client.

Embeddings are sent in batches to limit request size and keep worker memory
bounded. The OpenAI-compatible client is cached so batches can reuse HTTP
connections instead of creating a new TLS connection for every batch.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache, partial

from app.core.config import settings


@lru_cache(maxsize=1)
def _openai_client():
    import httpx
    from openai import OpenAI

    return OpenAI(
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        timeout=httpx.Timeout(
            settings.EMBEDDING_TIMEOUT_SECONDS,
            connect=settings.EMBEDDING_CONNECT_TIMEOUT_SECONDS,
        ),
        max_retries=settings.EMBEDDING_MAX_RETRIES,
    )


def _embed_batch_sync(texts: list[str]) -> list[list[float]]:
    if settings.EMBEDDING_PROVIDER == "openai":
        response = _openai_client().embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts,
        )
        # Preserve input order explicitly using the API's item index.
        return [
            item.embedding
            for item in response.data
        ]

    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Batch `texts` according to EMBEDDING_BATCH_SIZE and embed each batch."""
    if not texts:
        return []

    all_vectors: list[list[float]] = []
    batch_size = settings.EMBEDDING_BATCH_SIZE
    if batch_size < 1:
        raise ValueError("EMBEDDING_BATCH_SIZE must be greater than zero")

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        all_vectors.extend(_embed_batch_sync(batch))

    return all_vectors


async def embed_texts(texts: list[str]) -> list[list[float]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(embed_texts_sync, texts))


async def embed_query(query: str) -> list[float]:
    vectors = await embed_texts([query])
    if not vectors:
        raise ValueError("Cannot embed an empty query")
    return vectors[0]
