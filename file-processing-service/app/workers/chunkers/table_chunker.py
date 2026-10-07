"""
table_chunker: converts a raw {"kind": "table", "rows": [[...]]} block into one or
more markdown-table-formatted chunk contents, preserving row/column structure
(never flattening a table into plain prose, which would lose alignment between
values and their column headers). Splits further if the row count still exceeds
MAX_TABLE_ROWS_PER_CHUNK after the extractor's own pre-batching (e.g. docx tables,
which extractors don't pre-batch the way xlsx_extractor does).
"""
from __future__ import annotations

from app.core.config import settings


def _cell_to_str(cell) -> str:
    """PyMuPDF's find_tables().extract() returns None (not "") for empty cells,
    so every cell must be explicitly normalized before joining — otherwise
    "".join()/" | ".join() raises TypeError on the first None it hits."""
    return "" if cell is None else str(cell)


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header, *body = rows
    header_cells = [_cell_to_str(c) for c in header]
    lines = ["| " + " | ".join(header_cells) + " |", "| " + " | ".join(["---"] * len(header_cells)) + " |"]
    for row in body:
        # pad/truncate to header length defensively (malformed docx/pdf tables sometimes vary),
        # then normalize every cell (including None values already present, not just missing ones)
        padded = (row + [""] * len(header_cells))[: len(header_cells)]
        lines.append("| " + " | ".join(_cell_to_str(c) for c in padded) + " |")
    return "\n".join(lines)

def chunk_table(rows: list[list[str]], max_rows: int | None = None, max_chars: int | None = None) -> list[str]:
    """
    Splits a table into markdown chunks of at most `max_rows` body rows AND at most
    ~`max_chars` characters (wide sheets with many columns would otherwise blow past
    the embedding model's input limit). The header row is repeated in every chunk so
    each chunk is self-describing.
    """
    max_rows = max_rows or settings.MAX_TABLE_ROWS_PER_CHUNK
    max_chars = max_chars or settings.MAX_TABLE_CHUNK_CHARS
    if not rows:
        return []

    header, body = rows[0], rows[1:]
    if not body:
        return [_rows_to_markdown([header])]

    header_len = len(_rows_to_markdown([header]))
    chunks: list[str] = []
    batch: list[list[str]] = []
    batch_len = header_len
    for row in body:
        row_len = len(_rows_to_markdown([header, row])) - header_len
        if batch and (len(batch) >= max_rows or batch_len + row_len > max_chars):
            chunks.append(_rows_to_markdown([header] + batch))
            batch, batch_len = [], header_len
        batch.append(row)
        batch_len += row_len
    if batch:
        chunks.append(_rows_to_markdown([header] + batch))
    return chunks
