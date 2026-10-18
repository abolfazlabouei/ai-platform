"""
PDF extractor using PyMuPDF.

Text extraction:
- Uses page.get_text("blocks") instead of page.get_text("words").
- Preserves the logical reading order already provided by PyMuPDF.
- NFKC-normalizes Arabic/Persian presentation-form glyphs.
- Removes Unicode Private Use Area characters such as U+F020.
- Keeps table extraction separate to avoid duplicating table text.

Output:
    {"kind": "paragraph"|"table"|"image", ...}
"""
from __future__ import annotations
import unicodedata
import pymupdf as fitz  # `fitz` is PyMuPDF's legacy import alias; `pymupdf` is the current package name
from app.workers.extractors.rtl_text import fix_rtl_cell
import re


def _clean_pdf_text(text: str | None) -> str | None:
    """
    Normalize extracted PDF text for Persian/Arabic documents.

    - NFKC converts Arabic/Persian presentation-form glyphs to normal Unicode.
    - Private Use Area characters (category 'Co'), such as U+F020, are removed.
    - Excess whitespace is cleaned while preserving line boundaries.
    """
    if text is None:
        return None

    text = unicodedata.normalize("NFKC", text)

    # Remove Private Use Area characters such as U+F020.
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) != "Co"
    )

    # Clean whitespace while preserving meaningful line breaks.
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove dotted/form placeholder lines.
        if re.fullmatch(r"[.\u00B7\u2022\u2026_\-\s]{4,}", line):
            continue

        line = " ".join(line.split())
        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _extract_text_blocks(page, table_bboxes: list[tuple[float, float, float, float]]) -> list[dict]:
    """
    Extract plain text using PyMuPDF block extraction.

    Each block keeps its bounding box so text overlapping detected tables
    can be excluded and therefore not duplicated.
    """
    blocks: list[dict] = []

    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue

        x0, y0, x1, y1, raw_text = block[:5]
        text = _clean_pdf_text(raw_text)

        if not text:
            continue

        # Ignore probable footer page-number-only blocks.
        # This document places page numbers near the lower part of the page.
        if (len(text) <= 4 and text.isdigit() and y0 >= page.rect.height * 0.75):
            continue

        overlaps_table = any(
            x0 < tb[2]
            and x1 > tb[0]
            and y0 < tb[3]
            and y1 > tb[1]
            for tb in table_bboxes
        )

        if overlaps_table:
            continue

        blocks.append(
            {
                "kind": "paragraph",
                "text": text,
                "bbox": [x0, y0, x1, y1],
            }
        )

    return blocks


def extract_pdf(raw_bytes: bytes) -> list[dict]:
    blocks: list[dict] = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")

    try:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            table_bboxes: list[tuple[float, float, float, float]] = []

            try:
                found_tables = page.find_tables()
                for table in found_tables.tables:
                    rows = table.extract()
                    if not rows:
                        continue

                    cleaned_rows = []
                    for row in rows:
                        cleaned_row = [
                            fix_rtl_cell(cell)
                            for cell in row
                        ]
                        cleaned_rows.append(cleaned_row)

                    blocks.append(
                        {
                            "kind": "table",
                            "rows": cleaned_rows,
                            "page": page_number,
                        }
                    )
                    table_bboxes.append(tuple(table.bbox))
            except Exception:  # noqa: BLE001 — table detection is best-effort, never fatal
                pass

            # --- Plain text ---
            text_blocks = _extract_text_blocks(page, table_bboxes)

            for block in text_blocks:
                blocks.append(
                    {
                        "kind": "paragraph",
                        "text": block["text"],
                        "page": page_number,
                    }
                )

            # --- embedded images ---
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception:  # noqa: BLE001
                    continue
                blocks.append(
                    {
                        "kind": "image",
                        "bytes": base_image["image"],
                        "content_type": f"image/{base_image['ext']}",
                        "filename": f"page{page_number}_img{img_index}.{base_image['ext']}",
                        "page": page_number,
                    }
                )
    finally:
        doc.close()

    return blocks