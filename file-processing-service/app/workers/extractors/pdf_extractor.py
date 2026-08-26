"""
PDF extractor. Uses PyMuPDF (fitz) for both text/layout and embedded image
extraction in a single pass (faster and simpler than combining pdfplumber for
tables + PyMuPDF for images); pdfplumber-style table detection is approximated
via PyMuPDF's `find_tables()` API (available from PyMuPDF 1.23+).

Text is extracted at the WORD level (page.get_text("words"), which includes
per-word bounding boxes) rather than PyMuPDF's higher-level "blocks" text mode,
specifically so rtl_text.fix_rtl_line can correct word order and glyph shaping
for Arabic/Persian PDFs whose content stream stores RTL text in left-to-right
visual order with presentation-form glyphs (see rtl_text.py's docstring for
why this happens and what the fix does).

Output: same raw-block shape as docx_extractor — {"kind": "paragraph"|"table"|"image", ...},
ordered per page.
"""
from __future__ import annotations

import pymupdf as fitz  # `fitz` is PyMuPDF's legacy import alias; `pymupdf` is the current package name

from app.workers.extractors.rtl_text import fix_rtl_cell, fix_rtl_line


def _group_words_into_lines(words: list[tuple]) -> list[tuple[int, str, list[float]]]:
    """
    Groups PyMuPDF's flat word list (each a tuple ending in block_no, line_no,
    word_no) into per-line entries, preserving each line's word order (needed
    by fix_rtl_line) and computing a bounding box per line (needed for the
    table-overlap check). Returns [(block_no, line_text, line_bbox), ...] in
    original encounter order.
    """
    lines: dict[tuple[int, int], dict] = {}
    line_order: list[tuple[int, int]] = []

    for x0, y0, x1, y1, word, block_no, line_no, _word_no in words:
        key = (block_no, line_no)
        if key not in lines:
            lines[key] = {"words": [], "bbox": [x0, y0, x1, y1]}
            line_order.append(key)
        entry = lines[key]
        entry["words"].append(word)
        bbox = entry["bbox"]
        bbox[0] = min(bbox[0], x0)
        bbox[1] = min(bbox[1], y0)
        bbox[2] = max(bbox[2], x1)
        bbox[3] = max(bbox[3], y1)

    result = []
    for key in line_order:
        block_no, _line_no = key
        entry = lines[key]
        line_text = fix_rtl_line(entry["words"])
        result.append((block_no, line_text, entry["bbox"]))
    return result


def _group_lines_into_blocks(line_entries: list[tuple[int, str, list[float]]]) -> list[dict]:
    """Joins consecutive lines sharing the same block_no into one paragraph
    block, with a combined bounding box (union of its lines' boxes) for the
    table-overlap check."""
    blocks_by_no: dict[int, dict] = {}
    block_order: list[int] = []

    for block_no, line_text, bbox in line_entries:
        if not line_text.strip():
            continue
        if block_no not in blocks_by_no:
            blocks_by_no[block_no] = {"lines": [], "bbox": list(bbox)}
            block_order.append(block_no)
        entry = blocks_by_no[block_no]
        entry["lines"].append(line_text)
        b = entry["bbox"]
        b[0] = min(b[0], bbox[0])
        b[1] = min(b[1], bbox[1])
        b[2] = max(b[2], bbox[2])
        b[3] = max(b[3], bbox[3])

    return [
        {"text": "\n".join(blocks_by_no[no]["lines"]), "bbox": blocks_by_no[no]["bbox"]}
        for no in block_order
    ]


def extract_pdf(raw_bytes: bytes) -> list[dict]:
    blocks: list[dict] = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")

    try:
        for page_index, page in enumerate(doc):
            # --- tables first (so their cell text isn't duplicated by plain text extraction) ---
            table_bboxes = []
            try:
                found_tables = page.find_tables()
                for table in found_tables.tables:
                    rows = table.extract()
                    if rows:
                        fixed_rows = [[fix_rtl_cell(cell) for cell in row] for row in rows]
                        blocks.append({"kind": "table", "rows": fixed_rows, "page": page_index + 1})
                        table_bboxes.append(table.bbox)
            except Exception:  # noqa: BLE001 — table detection is best-effort, never fatal
                pass

            # --- plain text, extracted word-by-word and reassembled line-by-line
            #     (see module docstring: this is what makes the RTL fix possible) ---
            words = page.get_text("words")
            line_entries = _group_words_into_lines(words)
            paragraph_blocks = _group_lines_into_blocks(line_entries)

            for para in paragraph_blocks:
                x0, y0, x1, y1 = para["bbox"]
                overlaps_table = any(
                    x0 < tb[2] and x1 > tb[0] and y0 < tb[3] and y1 > tb[1] for tb in table_bboxes
                )
                if not overlaps_table:
                    blocks.append({"kind": "paragraph", "text": para["text"], "page": page_index + 1})

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
                        "filename": f"page{page_index + 1}_img{img_index}.{base_image['ext']}",
                        "page": page_index + 1,
                    }
                )
    finally:
        doc.close()

    return blocks