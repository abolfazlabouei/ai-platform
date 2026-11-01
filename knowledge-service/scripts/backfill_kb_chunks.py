"""
One-off backfill for hybrid search: copies the text of chunks that were ingested
BEFORE the kb_chunks table existed from Qdrant into Postgres, so the lexical
retriever can see them (otherwise only files re-ingested after the upgrade are
searchable by keyword).

Run once after `alembic upgrade head`, from the knowledge-service directory:

    python -m scripts.backfill_kb_chunks

Idempotent: rows that already exist (same knowledge_base_id + chunk_id) are skipped.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.kb_chunk import KBChunk
from app.models.knowledge_base import KnowledgeBase
from app.services.text_normalize import has_enough_text, normalize_text
from app.services.vector_store import _collection_name, _get_client
from app.workers.db import SyncSessionLocal


def main() -> None:
    client = _get_client()
    session = SyncSessionLocal()
    total = 0
    try:
        for kb_id in session.scalars(select(KnowledgeBase.id)).all():
            name = _collection_name(str(kb_id))
            try:
                client.get_collection(name)
            except Exception:  # noqa: BLE001 — KB never ingested anything
                continue
            offset = None
            while True:
                points, offset = client.scroll(
                    collection_name=name, limit=256, offset=offset, with_payload=True, with_vectors=False
                )
                rows = []
                for p in points:
                    payload = p.payload or {}
                    content = normalize_text(payload.get("content"))
                    if not payload.get("chunk_id") or not payload.get("file_id") or not has_enough_text(content):
                        continue
                    rows.append(
                        {
                            "id": uuid.uuid4(),
                            "knowledge_base_id": kb_id,
                            "file_id": uuid.UUID(str(payload["file_id"])),
                            "chunk_id": uuid.UUID(str(payload["chunk_id"])),
                            "content": content,
                            "type": payload.get("type"),
                            "order_index": payload.get("order_index"),
                        }
                    )
                if rows:
                    session.execute(
                        insert(KBChunk).values(rows).on_conflict_do_nothing(constraint="uq_kb_chunks_kb_chunk")
                    )
                    session.commit()
                    total += len(rows)
                if offset is None:
                    break
            print(f"KB {kb_id}: done")
        print(f"Backfilled up to {total} chunks")
    finally:
        session.close()


if __name__ == "__main__":
    main()
