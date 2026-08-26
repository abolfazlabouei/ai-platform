"""
The ingest pipeline for a single (knowledge_base, file) pair, run as one Celery task.

Pulls the file's chunks from file-processing-service (GET /files/{id}/chunks),
embeds their text content in batches, and upserts vectors into the knowledge
base's Qdrant collection with metadata (chunk_id, file_id, type, content) so
/search can return exactly what chat-agent-service's knowledge_retrieval node needs.

Note on image chunks: they're embedded using their caption text (the same
placeholder/caption produced by file-processing-service's image_chunker). If a
vision-embedding model is introduced later, this is the single place to branch on
chunk["type"] == "image" and call a different embedding path — nothing else in
this service needs to change.
"""
from __future__ import annotations

import uuid

from app.models.job import Job, JobStage
from app.models.kb_source import IngestStatus, KBSource
from app.services.embedding_service import embed_texts_sync
from app.services.file_client import get_chunks_sync
from app.services.progress_publisher import publish_progress_sync
from app.services.vector_store import upsert_vectors_sync
from app.workers.celery_app import celery_app
from app.workers.db import SyncSessionLocal


@celery_app.task(name="embed_kb_source", bind=True)
def embed_kb_source(self, kb_source_id: str, job_id: str) -> None:
    session = SyncSessionLocal()
    try:
        kb_source = session.get(KBSource, uuid.UUID(kb_source_id))
        job_row = session.get(Job, uuid.UUID(job_id))
        if kb_source is None or job_row is None:
            return

        try:
            # --- stage: fetch chunks ---
            kb_source.status = IngestStatus.EMBEDDING
            job_row.stage = JobStage.EMBEDDING
            session.commit()
            publish_progress_sync(job_id, "embedding", 10, "Fetching chunks from file-processing-service")

            chunks = get_chunks_sync(str(kb_source.file_id))
            if not chunks:
                kb_source.status = IngestStatus.DONE
                job_row.stage = JobStage.DONE
                session.commit()
                publish_progress_sync(job_id, "done", 100, "No chunks found for this file")
                return

            # --- stage: embed ---
            texts = [c["content"] for c in chunks]
            publish_progress_sync(job_id, "embedding", 30, f"Embedding {len(texts)} chunks")
            vectors = embed_texts_sync(texts)

            # --- stage: upsert into vector store ---
            points = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                points.append(
                    {
                        "id": str(uuid.uuid4()),
                        "vector": vector,
                        "payload": {
                            "chunk_id": chunk["id"],
                            "file_id": chunk["file_id"],
                            "type": chunk["type"],
                            "content": chunk["content"],
                            "order_index": chunk["order_index"],
                        },
                    }
                )
            upsert_vectors_sync(str(kb_source.knowledge_base_id), points)
            publish_progress_sync(job_id, "embedding", 90, "Upserted vectors into Qdrant")

            # --- stage: done ---
            kb_source.status = IngestStatus.DONE
            kb_source.chunks_embedded = len(points)
            job_row.stage = JobStage.DONE
            session.commit()
            publish_progress_sync(job_id, "done", 100, f"Embedded {len(points)} chunks")

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            kb_source.status = IngestStatus.FAILED
            kb_source.error = str(exc)
            job_row.stage = JobStage.FAILED
            job_row.error = str(exc)
            session.commit()
            publish_progress_sync(job_id, "failed", 100, str(exc))
            raise
    finally:
        session.close()
