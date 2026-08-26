"""Smoke test for markdown_extractor covering headings, paragraphs, and tables."""
from app.workers.extractors.markdown_extractor import extract_markdown

SAMPLE_MD = b"""# Title

Some intro paragraph.

| Name | Age |
| --- | --- |
| Alice | 30 |
| Bob | 25 |
"""


def test_extract_markdown_headings_paragraphs_tables():
    blocks = extract_markdown(SAMPLE_MD)
    kinds = [b["kind"] for b in blocks]
    assert "paragraph" in kinds
    assert "table" in kinds

    heading_block = next(b for b in blocks if b["kind"] == "paragraph" and b["text"].startswith("#"))
    assert "Title" in heading_block["text"]

    table_block = next(b for b in blocks if b["kind"] == "table")
    # rows[0] is the header — consistent with table_chunker.chunk_table's expectations
    assert table_block["rows"][0] == ["Name", "Age"]
    assert table_block["rows"][1] == ["Alice", "30"]
    assert table_block["rows"][2] == ["Bob", "25"]
