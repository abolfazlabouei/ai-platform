"""Smoke tests for the pure-function chunkers (no DB/storage/network involved)."""
from app.workers.chunkers.table_chunker import chunk_table
from app.workers.chunkers.text_chunker import chunk_paragraphs


def test_text_chunker_respects_chunk_size():
    paragraphs = ["A" * 500, "B" * 500, "C" * 500]
    chunks = chunk_paragraphs(paragraphs, chunk_size=600, overlap=0)
    assert all(len(c) <= 600 for c in chunks)
    assert len(chunks) >= 2


def test_text_chunker_empty_input_returns_empty():
    assert chunk_paragraphs([]) == []


def test_table_chunker_single_chunk_when_small():
    rows = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]
    chunks = chunk_table(rows, max_rows=10)
    assert len(chunks) == 1
    assert "Name" in chunks[0]
    assert "Alice" in chunks[0]


def test_table_chunker_splits_large_tables_and_repeats_header():
    header = ["col"]
    rows = [header] + [[str(i)] for i in range(25)]
    chunks = chunk_table(rows, max_rows=10)
    assert len(chunks) == 3  # 25 rows / 10 per chunk -> 3 chunks
    for c in chunks:
        assert "col" in c  # header repeated in every chunk
