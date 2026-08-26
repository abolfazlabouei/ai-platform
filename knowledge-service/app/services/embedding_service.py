"""
embedding_service: provider-agnostic embedding client, batched to respect API
rate limits and keep Celery task memory bounded on large files. Add a new branch
in `_embed_batch_sync` to support another provider — nothing else changes.

Both a sync (Celery) and async (FastAPI, e.g. for a future /search-by-text debug
endpoint) entrypoint are exposed, same pattern as the rest of this service.
"""
from __future__ import annotations

import asyncio
from functools import partial

from app.core.config import settings


def _embed_batch_sync(texts: list[str]) -> list[list[float]]:
    if settings.EMBEDDING_PROVIDER == "openai":
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,  
        )
        response = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=texts)
        return [item.embedding for item in response.data]

    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Batches `texts` into groups of EMBEDDING_BATCH_SIZE and embeds each group."""
    all_vectors: list[list[float]] = []
    batch_size = settings.EMBEDDING_BATCH_SIZE
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        all_vectors.extend(_embed_batch_sync(batch))
    return all_vectors


async def embed_texts(texts: list[str]) -> list[list[float]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(embed_texts_sync, texts))


async def embed_query(query: str) -> list[float]:
    vectors = await embed_texts([query])
    return vectors[0]
