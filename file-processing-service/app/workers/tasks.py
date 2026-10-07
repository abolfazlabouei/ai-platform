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

import hashlib
import logging
import uuid

from app.core.config import settings
from app.models.chunk import Chunk, ChunkType
from app.models.file import File, FileStatus, FileType
from app.models.job import Job, JobStage
from app.services.progress_publisher import publish_progress_sync
from app.storage.object_store import get_object_sync
from app.workers.celery_app import celery_app
from app.workers import vision
from app.workers.chunkers.image_chunker import store_image
from app.workers.chunkers.table_chunker import chunk_table
from app.workers.chunkers.text_chunker import chunk_paragraphs
from app.workers.db import SyncSessionLocal
from app.workers.extractors.docx_extractor import extract_docx
from app.workers.extractors.markdown_extractor import extract_markdown
from app.workers.extractors.pdf_extractor import extract_pdf
from app.workers.extractors.xlsx_extractor import extract_xlsx

logger = logging.getLogger(__name__)

_EXTRACTORS = {
    FileType.DOCX: extract_docx,
    FileType.PDF: extract_pdf,
    FileType.XLSX: extract_xlsx,
    FileType.MARKDOWN: extract_markdown,
}


def _clean(text: str) -> str:
    # Postgres TEXT can't store NUL bytes (some PDFs contain them) — strip them.
    return text.replace("\x00", "").strip()


def _source_header(filename: str, block: dict | None) -> str:
    """One short line prefixed to every chunk: tells the embedding (and the chat
    model reading retrieved context) which file/page/sheet the content is from."""
    parts = [f"منبع: {filename}"]
    if block:
        if block.get("page"):
            parts.append(f"صفحه {block['page']}")
        if block.get("sheet_name"):
            parts.append(f"شیت {block['sheet_name']}")
    return "[" + " | ".join(parts) + "]"


def _caption_images(raw_blocks: list[dict]) -> dict[int, dict]:
    """
    Normalizes, filters (tiny icons, duplicates, EMF/WMF) and describes every image
    block with the vision model, in parallel. Returns {block_index: {"png", "caption"}}
    only for images that got a usable description.
    """
    if not vision.vision_enabled():
        n = sum(1 for b in raw_blocks if b["kind"] == "image")
        if n:
            logger.warning("VISION_API_KEY not set: skipping %d image(s) (they won't be searchable)", n)
        return {}

    candidates: list[tuple[int, bytes, str]] = []
    seen_hashes: set[str] = set()
    for idx, block in enumerate(raw_blocks):
        if block["kind"] != "image":
            continue
        normalized = vision.normalize_image(block["bytes"])
        if normalized is None:
            continue
        png, width, height = normalized
        if min(width, height) < settings.IMAGE_MIN_SIDE_PX:
            continue
        digest = hashlib.sha1(png).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        candidates.append((idx, png, block.get("context") or ""))

    captions = vision.run_parallel(lambda c: vision.describe_image(c[1], c[2] or None), candidates)
    return {idx: {"png": png, "caption": cap} for (idx, png, _ctx), cap in zip(candidates, captions, strict=True) if cap}


def _build_chunks(file_id: uuid.UUID, raw_blocks: list[dict], filename: str = "") -> list[Chunk]:
    """
    Groups consecutive paragraph blocks together before text-chunking them (so
    chunk boundaries can span multiple paragraphs up to chunk_size), while tables
    and images are chunked individually and immediately, preserving their position
    in the overall order_index sequence. Every chunk starts with a source line
    (file / page / sheet) — see _source_header.
    """
    image_results = _caption_images(raw_blocks)

    chunks: list[Chunk] = []
    order_index = 0
    pending_paragraphs: list[str] = []
    pending_first_block: dict | None = None

    def _add(chunk_type: ChunkType, body: str, block: dict | None, **extra):
        nonlocal order_index
        body = _clean(body)
        if not body:
            return
        chunks.append(
            Chunk(
                file_id=file_id,
                type=chunk_type,
                content=f"{_source_header(filename, block)}\n{body}",
                order_index=order_index,
                **extra,
            )
        )
        order_index += 1

    def _flush_paragraphs():
        nonlocal pending_first_block
        if not pending_paragraphs:
            return
        for text in chunk_paragraphs(pending_paragraphs):
            meta = {"page": pending_first_block["page"]} if pending_first_block and pending_first_block.get("page") else {}
            _add(ChunkType.TEXT, text, pending_first_block, extra_metadata=meta)
        pending_paragraphs.clear()
        pending_first_block = None

    for idx, block in enumerate(raw_blocks):
        kind = block["kind"]

        if kind == "paragraph":
            text = _clean(block["text"])
            if not text:
                continue
            # a new page starts a new text group, so chunk source lines stay accurate
            if pending_first_block and block.get("page") != pending_first_block.get("page"):
                _flush_paragraphs()
            if not pending_paragraphs:
                pending_first_block = block
            pending_paragraphs.append(text)
            continue

        # any non-paragraph block flushes accumulated paragraph text first, to keep
        # order_index reflecting true document order
        _flush_paragraphs()

        if kind == "table":
            rows = [[_clean(str(c)) if c is not None else "" for c in row] for row in block["rows"]]
            meta = {k: v for k, v in block.items() if k not in ("kind", "rows")}
            for md_table in chunk_table(rows):
                _add(ChunkType.TABLE, md_table, block, extra_metadata=meta)

        elif kind == "image":
            result = image_results.get(idx)
            if not result:
                continue  # undescribable image: not indexed (see image_chunker docstring)
            storage_key = store_image(result["png"])
            meta = {"content_type": "image/png"}
            if block.get("page"):
                meta["page"] = block["page"]
            _add(ChunkType.IMAGE, "[تصویر]\n" + result["caption"], block, storage_key=storage_key, extra_metadata=meta)

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

            chunks = _build_chunks(file_row.id, raw_blocks, file_row.filename)
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
