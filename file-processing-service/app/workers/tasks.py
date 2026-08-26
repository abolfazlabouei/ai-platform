"""
The extraction + chunking pipeline, run as a single Celery task per file.

Design note: extraction and chunking are implemented as two distinct *modules*
(workers/extractors/*, workers/chunkers/*) to keep them independently testable and
swappable, but they run as ONE Celery task rather than a `chain(extract.s() |
chunk.s())` of two tasks. Reason: extracted raw blocks for a large PDF/xlsx can be
tens of thousands of small dicts (including raw image bytes) — passing that through
Celery's result backend (Redis) as an intermediate hop would double the Redis
traffic and serialization cost for no benefit, since both steps always run
back-to-back for the same file anyway. Progress is still published stage-by-stage
so the frontend sees an "extracting -> chunking -> done" progression identical to
what a two-task chain would report.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.models.chunk import Chunk, ChunkType
from app.models.file import File, FileStatus, FileType
from app.models.job import Job, JobStage
from app.services.progress_publisher import publish_progress_sync
from app.storage.object_store import get_object_sync
from app.workers.celery_app import celery_app
from app.workers.chunkers.image_chunker import chunk_image
from app.workers.chunkers.table_chunker import chunk_table
from app.workers.chunkers.text_chunker import chunk_paragraphs
from app.workers.db import SyncSessionLocal
from app.workers.extractors.docx_extractor import extract_docx
from app.workers.extractors.markdown_extractor import extract_markdown
from app.workers.extractors.pdf_extractor import extract_pdf
from app.workers.extractors.xlsx_extractor import extract_xlsx

_EXTRACTORS = {
    FileType.DOCX: extract_docx,
    FileType.PDF: extract_pdf,
    FileType.XLSX: extract_xlsx,
    FileType.MARKDOWN: extract_markdown,
}


def _build_chunks(file_id: uuid.UUID, raw_blocks: list[dict]) -> list[Chunk]:
    """
    Groups consecutive paragraph blocks together before text-chunking them (so
    chunk boundaries can span multiple paragraphs up to chunk_size), while tables
    and images are chunked individually and immediately, preserving their position
    in the overall order_index sequence.
    """
    chunks: list[Chunk] = []
    order_index = 0
    pending_paragraphs: list[str] = []

    def _flush_paragraphs():
        nonlocal order_index
        if not pending_paragraphs:
            return
        for text in chunk_paragraphs(pending_paragraphs):
            chunks.append(
                Chunk(file_id=file_id, type=ChunkType.TEXT, content=text, order_index=order_index)
            )
            order_index += 1
        pending_paragraphs.clear()

    for block in raw_blocks:
        kind = block["kind"]

        if kind == "paragraph":
            pending_paragraphs.append(block["text"])
            continue

        # any non-paragraph block flushes accumulated paragraph text first, to keep
        # order_index reflecting true document order
        _flush_paragraphs()

        if kind == "table":
            for md_table in chunk_table(block["rows"]):
                meta = {k: v for k, v in block.items() if k not in ("kind", "rows")}
                chunks.append(
                    Chunk(
                        file_id=file_id,
                        type=ChunkType.TABLE,
                        content=md_table,
                        order_index=order_index,
                        extra_metadata=meta,
                    )
                )
                order_index += 1

        elif kind == "image":
            result = chunk_image(block["bytes"], block["content_type"], block["filename"])
            chunks.append(
                Chunk(
                    file_id=file_id,
                    type=ChunkType.IMAGE,
                    content=result["content"],
                    storage_key=result["storage_key"],
                    order_index=order_index,
                    extra_metadata={"content_type": block["content_type"]},
                )
            )
            order_index += 1

    _flush_paragraphs()
    return chunks


@celery_app.task(name="process_file", bind=True)
def process_file(self, file_id: str, job_id: str) -> None:
    session = SyncSessionLocal()
    try:
        file_row = session.get(File, uuid.UUID(file_id))
        job_row = session.get(Job, uuid.UUID(job_id))
        if file_row is None or job_row is None:
            return

        try:
            # --- stage: extracting ---
            file_row.status = FileStatus.EXTRACTING
            job_row.stage = JobStage.EXTRACTING
            session.commit()
            publish_progress_sync(job_id, "extracting", 10, f"Extracting {file_row.filename}")

            extractor = _EXTRACTORS.get(file_row.file_type)
            if extractor is None:
                raise ValueError(f"No extractor registered for file type {file_row.file_type}")

            raw_bytes = get_object_sync(settings.S3_BUCKET_RAW, file_row.storage_key)
            raw_blocks = extractor(raw_bytes)
            publish_progress_sync(job_id, "extracting", 50, f"Extracted {len(raw_blocks)} raw blocks")

            # --- stage: chunking ---
            file_row.status = FileStatus.CHUNKING
            job_row.stage = JobStage.CHUNKING
            session.commit()
            publish_progress_sync(job_id, "chunking", 60, "Chunking extracted content")

            chunks = _build_chunks(file_row.id, raw_blocks)
            session.add_all(chunks)

            # --- stage: done ---
            file_row.status = FileStatus.DONE
            job_row.stage = JobStage.DONE
            session.commit()
            publish_progress_sync(job_id, "done", 100, f"Created {len(chunks)} chunks")

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            file_row.status = FileStatus.FAILED
            file_row.error = str(exc)
            job_row.stage = JobStage.FAILED
            job_row.error = str(exc)
            session.commit()
            publish_progress_sync(job_id, "failed", 100, str(exc))
            raise
    finally:
        session.close()
