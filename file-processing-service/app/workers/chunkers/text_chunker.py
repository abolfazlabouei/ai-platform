"""
text_chunker: a dependency-light recursive character splitter (no LangChain
dependency needed here — this service only produces chunks, it doesn't need any
LLM-framework tooling). Splits on paragraph boundaries first, then sentences,
then raw characters as a last resort, respecting chunk_size/overlap.

Input: a list of paragraph raw-block texts (already extracted, in document order).
Output: list[str] chunk contents.
"""
from __future__ import annotations

from app.core.config import settings

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _split_text(text: str, chunk_size: int, separators: list[str]) -> list[str]:
    if len(text) <= chunk_size or not separators:
        return [text]

    sep, *rest_separators = separators
    if sep == "":
        # last resort: hard character split
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    parts = text.split(sep)
    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = current + sep + part if current else part
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) > chunk_size:
                chunks.extend(_split_text(part, chunk_size, rest_separators))
                current = ""
            else:
                current = part
    if current:
        chunks.append(current)
    return chunks


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap:]
        result.append(prev_tail + chunks[i])
    return result


def chunk_paragraphs(
    paragraph_texts: list[str],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    chunk_size = chunk_size or settings.TEXT_CHUNK_SIZE
    overlap = overlap if overlap is not None else settings.TEXT_CHUNK_OVERLAP

    full_text = "\n\n".join(paragraph_texts)
    if not full_text.strip():
        return []

    raw_chunks = _split_text(full_text, chunk_size, _SEPARATORS)
    return _add_overlap(raw_chunks, overlap)
