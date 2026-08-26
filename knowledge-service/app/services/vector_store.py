"""
vector_store: thin wrapper around qdrant-client. One Qdrant collection per
KnowledgeBase (named f"{QDRANT_COLLECTION_PREFIX}{kb_id}"), so deleting a
knowledge base is just dropping its collection — no cross-tenant filtering needed
within a single collection, which keeps queries simple and fast.

Exposes both a sync API (used inside Celery embed_tasks) and an async API (used by
the /search endpoint), mirroring the pattern used in file-processing-service's
object_store.py.
"""
from __future__ import annotations

import asyncio
import uuid
from functools import partial

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.QDRANT_URL)
    return _client


def _collection_name(kb_id: str) -> str:
    return f"{settings.QDRANT_COLLECTION_PREFIX}{kb_id}"


# --- sync API (Celery embed_tasks) ---


def ensure_collection_sync(kb_id: str) -> None:
    client = _get_client()
    name = _collection_name(kb_id)
    existing = [c.name for c in client.get_collections().collections]
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=settings.EMBEDDING_DIMENSIONS, distance=qmodels.Distance.COSINE
            ),
        )


def upsert_vectors_sync(kb_id: str, points: list[dict]) -> None:
    """points: [{"id": str, "vector": list[float], "payload": {...}}]"""
    client = _get_client()
    ensure_collection_sync(kb_id)
    client.upsert(
        collection_name=_collection_name(kb_id),
        points=[
            qmodels.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points
        ],
    )


def delete_by_file_sync(kb_id: str, file_id: str) -> None:
    client = _get_client()
    client.delete(
        collection_name=_collection_name(kb_id),
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="file_id", match=qmodels.MatchValue(value=file_id))]
            )
        ),
    )


def delete_collection_sync(kb_id: str) -> None:
    client = _get_client()
    client.delete_collection(collection_name=_collection_name(kb_id))


def search_sync(kb_ids: list[str], query_vector: list[float], top_k: int) -> list[dict]:
    client = _get_client()
    all_hits: list[dict] = []
    for kb_id in kb_ids:
        name = _collection_name(kb_id)
        try:
            hits = client.search(collection_name=name, query_vector=query_vector, limit=top_k)
        except Exception:  # noqa: BLE001 — collection may not exist yet (empty kb)
            continue
        for hit in hits:
            all_hits.append(
                {
                    "score": hit.score,
                    "chunk_id": hit.payload.get("chunk_id"),
                    "file_id": hit.payload.get("file_id"),
                    "knowledge_base_id": kb_id,
                    "content": hit.payload.get("content"),
                    "type": hit.payload.get("type"),
                }
            )
    all_hits.sort(key=lambda h: h["score"], reverse=True)
    return all_hits[:top_k]


# --- async API (FastAPI /search endpoint) ---


async def search(kb_ids: list[str], query_vector: list[float], top_k: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(search_sync, kb_ids, query_vector, top_k))


async def delete_collection(kb_id: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(delete_collection_sync, kb_id))


def new_point_id() -> str:
    return str(uuid.uuid4())
