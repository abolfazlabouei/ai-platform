"""
XLSX extractor. Each worksheet becomes ONE "table" raw block whose first row is the
sheet's header row; table_chunker.py then splits it into chunks and repeats that
header in every chunk.

(Previous version pre-split sheets into 30-row batches here, which meant every
batch after the first had a DATA row treated as its header — rows 31+ lost their
column names, which made questions about most of a large sheet unanswerable.)

Also:
- trailing/fully-empty rows and columns are dropped (Excel often reports formatted
  but empty cells far beyond the real data);
- numbers/dates are formatted the way a person reads them (12.0 -> "12",
  datetime -> "2024-05-01");
- images/charts embedded as pictures (xl/media/*) are emitted as image blocks.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile

import openpyxl

_IMAGE_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    return str(value).strip()


def _clean_sheet(raw_rows: list[list[str]]) -> list[list[str]]:
    rows = [r for r in raw_rows if any(c for c in r)]
    if not rows:
        return []
    width = max(max((i + 1 for i, c in enumerate(r) if c), default=0) for r in rows)
    return [(r + [""] * width)[:width] for r in rows]


def extract_xlsx(raw_bytes: bytes) -> list[dict]:
    blocks: list[dict] = []
    workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
    try:
        for sheet in workbook.worksheets:
            raw_rows = [[_fmt(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
            rows = _clean_sheet(raw_rows)
            if rows:
                blocks.append({"kind": "table", "rows": rows, "sheet_name": sheet.title})
    finally:
        workbook.close()

    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        for name in sorted(n for n in zf.namelist() if n.startswith("xl/media/")):
            ext = name.rsplit(".", 1)[-1].lower()
            blocks.append(
                {
                    "kind": "image",
                    "bytes": zf.read(name),
                    "content_type": _IMAGE_EXT_TO_MIME.get(ext, "application/octet-stream"),
                    "filename": name,
                    "context": "",
                }
            )
    return blocks
