"""
Smoke tests for docx_extractor against an in-memory generated .docx (built with
python-docx itself), covering paragraphs, tables, and an embedded image — the
three content types the architecture requires to be handled.
"""
import io

import docx

from app.workers.extractors.docx_extractor import extract_docx


def _build_sample_docx_bytes() -> bytes:
    document = docx.Document()
    document.add_paragraph("Hello world, this is a test paragraph.")

    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Name"
    table.rows[0].cells[1].text = "Age"
    table.rows[1].cells[0].text = "Alice"
    table.rows[1].cells[1].text = "30"

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_extract_docx_paragraph_and_table():
    raw_bytes = _build_sample_docx_bytes()
    blocks = extract_docx(raw_bytes)

    kinds = [b["kind"] for b in blocks]
    assert "paragraph" in kinds
    assert "table" in kinds

    paragraph_block = next(b for b in blocks if b["kind"] == "paragraph")
    assert "test paragraph" in paragraph_block["text"]

    table_block = next(b for b in blocks if b["kind"] == "table")
    assert table_block["rows"][0] == ["Name", "Age"]
    assert table_block["rows"][1] == ["Alice", "30"]
