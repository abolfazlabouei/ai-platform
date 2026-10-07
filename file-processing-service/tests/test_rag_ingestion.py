"""Regression tests for the RAG ingestion fixes (no network, no DB, no MinIO)."""
import datetime
import io

import docx
import openpyxl
import pymupdf

from app.workers.chunkers.table_chunker import chunk_table
from app.workers.extractors.docx_extractor import extract_docx
from app.workers.extractors.xlsx_extractor import extract_xlsx
from app.workers.vision import looks_garbled_rtl, markdown_to_blocks, normalize_image


def _png(w=300, h=200) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def test_xlsx_every_chunk_keeps_the_real_header():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["کد", "نام", "قیمت", "تاریخ"])
    for i in range(1, 76):
        ws.append([i, f"خدمت {i}", 1000.0 * i, datetime.datetime(2024, 1, 1)])
    buf = io.BytesIO()
    wb.save(buf)

    blocks = extract_xlsx(buf.getvalue())
    tables = [b for b in blocks if b["kind"] == "table"]
    assert len(tables) == 1  # one block per sheet; splitting happens in table_chunker
    chunks = chunk_table(tables[0]["rows"], max_rows=30)
    assert len(chunks) == 3
    for c in chunks:
        assert c.splitlines()[0] == "| کد | نام | قیمت | تاریخ |"
    assert "| 31 | خدمت 31 | 31000 | 2024-01-01 |" in chunks[1]  # 31000.0 -> 31000, datetime -> date


def test_xlsx_trims_empty_rows_and_columns():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["B1"] = "a", "b"
    ws["A2"], ws["B2"] = 1, 2
    ws.cell(row=50, column=20).value = None
    buf = io.BytesIO()
    wb.save(buf)
    rows = extract_xlsx(buf.getvalue())[0]["rows"]
    assert rows == [["a", "b"], ["1", "2"]]


def test_table_chunker_respects_char_budget_and_repeats_header():
    header = [f"col{i}" for i in range(20)]
    rows = [header] + [[f"value-{r}-{c}" for c in range(20)] for r in range(30)]
    chunks = chunk_table(rows, max_rows=30, max_chars=1500)
    assert len(chunks) > 1
    assert all(len(c) <= 1500 + 400 for c in chunks)
    assert all(c.startswith("| col0 |") for c in chunks)


def test_docx_inline_image_position_and_merged_cells():
    d = docx.Document()
    d.add_heading("بخش اول", level=1)
    t = d.add_table(rows=2, cols=3)
    for i, h in enumerate(["الف", "ب", "ج"]):
        t.rows[0].cells[i].text = h
    m = t.rows[1].cells[0].merge(t.rows[1].cells[1])
    m.text = "ادغام"
    t.rows[1].cells[2].text = "۸"
    d.add_paragraph("متن قبل از تصویر")
    d.add_picture(io.BytesIO(_png()))
    d.add_paragraph("متن بعد از تصویر")
    buf = io.BytesIO()
    d.save(buf)

    blocks = extract_docx(buf.getvalue())
    kinds = [b["kind"] for b in blocks]
    assert kinds.count("image") == 1  # not duplicated by the word/media/ fallback
    img = next(b for b in blocks if b["kind"] == "image")
    assert kinds.index("image") < len(kinds) - 1  # inline, not dumped at the end
    assert "بخش اول" in img["context"]
    table = next(b for b in blocks if b["kind"] == "table")
    assert table["rows"][1] == ["ادغام", "", "۸"]  # aligned with the 3-column header
    assert blocks[0]["text"] == "# بخش اول"


def test_garbled_persian_detection():
    garbled = "ا زم لا ر لیز از بعد و هاییقبل قبت ا چهمر ۲ د؟۷ شو باعثسوختگیپوستمی ر یالیز ۲آ ی۸ بند جمع ۲ ۱ ئد زا ی موها ر لیز"
    normal = (
        "لیزر موهای زائد یکی از روش‌های رایج برای از بین بردن موهای ناخواسته است و "
        "معمولا چند جلسه درمان لازم است. قرمزی خفیف بعد از لیزر طبیعی است و ظرف یک روز از بین می‌رود."
    )
    assert looks_garbled_rtl(garbled)
    assert not looks_garbled_rtl(normal)


def test_markdown_ocr_output_becomes_table_and_paragraph_blocks():
    md = "# عنوان\nمتن\n\n| نام | قیمت |\n|---|---|\n| لیزر | ۱۰۰ |\nپایان"
    blocks = markdown_to_blocks(md, page=2)
    assert [b["kind"] for b in blocks] == ["paragraph", "table", "paragraph"]
    assert blocks[1]["rows"] == [["نام", "قیمت"], ["لیزر", "۱۰۰"]]
    assert all(b["page"] == 2 for b in blocks)


def test_normalize_image_rejects_non_images():
    assert normalize_image(b"not an image") is None
    png, w, h = normalize_image(_png(120, 90))
    assert (w, h) == (120, 90) and png[:4] == b"\x89PNG"
