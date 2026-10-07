"""
Vision helpers used by the extraction pipeline (sync — runs inside Celery).

- normalize_image(): any image bytes -> PNG + size, via PyMuPDF (no Pillow needed).
  Returns None for formats a vision API can't take (EMF/WMF, corrupt data).
- describe_image(): caption + verbatim text + chart/table data, for indexing.
- ocr_page():       full transcription of a rendered PDF page (tables -> markdown).
- markdown_to_blocks(): turns OCR markdown into paragraph/table raw blocks so OCR'd
  tables go through table_chunker (header repeated per chunk) like any other table.
- looks_garbled_rtl(): detects the broken Persian text layers some PDF generators
  produce (letters split into fragments), so those pages can be OCR'd instead.

Talks to any OpenAI-compatible /chat/completions endpoint with image_url parts
(OpenRouter, OpenAI, ...). Every call fails soft: returns None, never raises, so a
vision outage degrades quality instead of failing the whole file.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

import httpx
import pymupdf

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def vision_enabled() -> bool:
    return bool(settings.VISION_API_KEY)


# ---------------------------------------------------------------------------
# image normalization
# ---------------------------------------------------------------------------


def normalize_image(image_bytes: bytes) -> tuple[bytes, int, int] | None:
    """Returns (png_bytes, width, height) or None if the image can't be decoded."""
    try:
        pix = pymupdf.Pixmap(image_bytes)
        if pix.colorspace is None or pix.colorspace.n not in (1, 3):
            # CMYK / indexed / mask-only -> RGB (PNG writer only takes gray/RGB)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return pix.tobytes("png"), pix.width, pix.height
    except Exception:  # noqa: BLE001 — EMF/WMF/corrupt: not usable by a vision model
        return None


def pixmap_to_png(pix: pymupdf.Pixmap) -> bytes:
    if pix.colorspace is None or pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix.tobytes("png")


# ---------------------------------------------------------------------------
# vision API call
# ---------------------------------------------------------------------------


def _chat_with_image(prompt: str, png_bytes: bytes, max_tokens: int) -> str | None:
    if not vision_enabled():
        return None

    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    payload = {
        "model": settings.VISION_MODEL,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {settings.VISION_API_KEY}"}
    url = settings.VISION_BASE_URL.rstrip("/") + "/chat/completions"

    for attempt in range(settings.VISION_MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=settings.VISION_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"].get("content") or ""
                if isinstance(content, list):  # some providers return content parts
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                content = content.strip()
                return content or None
            logger.warning("vision call failed (%s): %s", resp.status_code, resp.text[:300])
            if resp.status_code < 500 and resp.status_code != 429:
                return None  # 4xx (bad key/model/image): retrying won't help
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision call error: %s", exc)
        time.sleep(2 * (attempt + 1))
    return None


_IMAGE_PROMPT = """You are indexing an image extracted from a document, so it can be found by search and used to answer questions.
Write, in {lang}:
1. One or two sentences describing what the image shows.
2. If the image contains ANY text (labels, titles, numbers, captions), transcribe it exactly, keeping the original language.
3. If it is a chart, diagram, table, form or screenshot, extract its data/structure. Render tables as GitHub markdown tables.
Output only that content — no preamble, no remarks about the image quality.
{context}"""

_PAGE_PROMPT = """Transcribe this document page completely and faithfully, in natural reading order (right-to-left for Persian/Arabic).
Rules:
- Keep the original language and wording exactly. Do not translate, summarize or correct.
- Render every table as a GitHub markdown table (first row = header), one table per block.
- Keep headings on their own lines.
- For photos/figures/charts, write one line: [تصویر: short description in {lang}, including any numbers or labels it shows].
- Skip page headers/footers that are only page numbers.
Output only the transcription."""


def describe_image(png_bytes: bytes, context: str | None = None) -> str | None:
    ctx = f"\nText around the image in the document (for context only): {context[:500]}" if context else ""
    return _chat_with_image(
        _IMAGE_PROMPT.format(lang=settings.VISION_OUTPUT_LANGUAGE, context=ctx), png_bytes, max_tokens=1200
    )


def ocr_page(png_bytes: bytes) -> str | None:
    return _chat_with_image(_PAGE_PROMPT.format(lang=settings.VISION_OUTPUT_LANGUAGE), png_bytes, max_tokens=4000)


def run_parallel(fn: Callable[[T], R], items: list[T]) -> list[R]:
    """Order-preserving parallel map (vision calls are network-bound)."""
    if not items:
        return []
    workers = max(1, min(settings.VISION_CONCURRENCY, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


# ---------------------------------------------------------------------------
# OCR markdown -> raw blocks
# ---------------------------------------------------------------------------

_SEPARATOR_ROW = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _split_md_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def markdown_to_blocks(markdown: str, page: int | None = None) -> list[dict]:
    text = re.sub(r"^```[a-zA-Z]*\s*$", "", markdown, flags=re.MULTILINE)  # stray code fences
    blocks: list[dict] = []
    para: list[str] = []
    table: list[list[str]] = []

    def flush_para():
        joined = "\n".join(para).strip()
        if joined:
            block = {"kind": "paragraph", "text": joined}
            if page is not None:
                block["page"] = page
            blocks.append(block)
        para.clear()

    def flush_table():
        if table:
            block = {"kind": "table", "rows": [r[:] for r in table]}
            if page is not None:
                block["page"] = page
            blocks.append(block)
        table.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.count("|") >= 2:
            flush_para()
            if not _SEPARATOR_ROW.match(line):
                table.append(_split_md_row(line))
            continue
        flush_table()
        if not line:
            flush_para()
        else:
            para.append(line)
    flush_para()
    flush_table()
    return blocks


# ---------------------------------------------------------------------------
# garbled RTL text-layer detection
# ---------------------------------------------------------------------------

_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_TOKEN = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]+")
# Single-letter words that are legitimate in normal Persian/Arabic text.
_VALID_SINGLE_LETTERS = {"و", "ی", "ب", "ک", "ء"}


def looks_garbled_rtl(text: str) -> bool:
    """
    Heuristic for broken Persian/Arabic PDF text layers. Normal Persian has almost no
    one-letter words except "و"; garbled layers (glyphs emitted in visual order /
    split at the wrong places) produce many stray single letters like "ا", "ر", "ز".
    Only judges pages that actually contain a meaningful amount of RTL text.
    """
    tokens = _TOKEN.findall(text)
    if len(tokens) < 15:
        return False
    stray = sum(1 for t in tokens if len(t) == 1 and t not in _VALID_SINGLE_LETTERS)
    return stray / len(tokens) > 0.08


def has_rtl(text: str) -> bool:
    return bool(_ARABIC_SCRIPT.search(text))
