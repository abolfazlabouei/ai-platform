"""
XLSX extractor. Each worksheet becomes one or more "table" raw blocks (large sheets
are pre-split into row-batches here already, since a 10,000-row sheet as a single
block would defeat the whole purpose of chunking — table_chunker.py then does any
further splitting needed to respect MAX_TABLE_ROWS_PER_CHUNK).
"""
from __future__ import annotations

import openpyxl

from app.core.config import settings


def extract_xlsx(raw_bytes: bytes) -> list[dict]:
    import io

    blocks: list[dict] = []
    workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)

    try:
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                # normalize None -> "" and everything to str for consistent downstream chunking
                rows.append(["" if cell is None else str(cell) for cell in row])

            if not rows:
                continue

            batch_size = settings.MAX_TABLE_ROWS_PER_CHUNK
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                blocks.append({"kind": "table", "rows": batch, "sheet_name": sheet.title})
    finally:
        workbook.close()

    return blocks
