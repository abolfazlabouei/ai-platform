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

def chunk_table(rows: list[list[str]], max_rows: int | None = None) -> list[str]:
    max_rows = max_rows or settings.MAX_TABLE_ROWS_PER_CHUNK
    if not rows:
        return []

    header = rows[0]
    body = rows[1:]

    if len(body) <= max_rows:
        return [_rows_to_markdown(rows)]

    chunks = []
    for start in range(0, len(body), max_rows):
        batch = [header] + body[start : start + max_rows]
        chunks.append(_rows_to_markdown(batch))
    return chunks
