"""
DOCX extractor.

Walks the document body in order (paragraphs and tables interleaved) and emits:
  {"kind": "paragraph", "text": str}
  {"kind": "table", "rows": list[list[str]]}
  {"kind": "image", "bytes": bytes, "content_type": str, "filename": str, "context": str}

Images are emitted at their real position: every <a:blip r:embed> (modern
drawings) and <v:imagedata r:id> (legacy VML) inside a paragraph or table is
resolved through the document's relationships to the actual image part. The
nearest heading + surrounding paragraph text is attached as `context`, which the
vision captioner uses to describe the image meaningfully. Any media file not
referenced from the body (e.g. headers, text boxes) is appended at the end so
nothing is silently lost.

Headings are prefixed with "#" so chunks keep section context. Horizontally
merged table cells (which python-docx repeats once per grid column) are emitted
once (its other column slots are left empty, so columns stay aligned with the
header).

These raw blocks are what chunkers/*.py consume — extractors never chunk themselves.
"""
from __future__ import annotations

import io
import zipfile

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

_IMAGE_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}

_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _iter_block_items(document):
    """Yields paragraphs and tables in document order (python-docx doesn't do this natively)."""
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _image_rel_ids(element) -> list[str]:
    ids = []
    for el in element.iter(_A_BLIP):
        rid = el.get(_R_EMBED)
        if rid:
            ids.append(rid)
    for el in element.iter(_V_IMAGEDATA):
        rid = el.get(_R_ID)
        if rid:
            ids.append(rid)
    return ids


def _heading_level(paragraph: Paragraph) -> int:
    try:
        name = (paragraph.style.name or "").lower()
    except Exception:  # noqa: BLE001
        return 0
    if name == "title":
        return 1
    if name.startswith("heading"):
        digits = "".join(ch for ch in name if ch.isdigit())
        return min(int(digits), 6) if digits else 1
    return 0


def _table_rows(table: Table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            key = id(cell._tc)
            # horizontally merged cell is repeated by python-docx once per grid column:
            # keep the column slot (alignment with the header) but don't repeat the text
            cells.append("" if key in seen else cell.text.strip())
            seen.add(key)
        if any(cells):
            rows.append(cells)
    return rows


def extract_docx(raw_bytes: bytes) -> list[dict]:
    document = DocxDocument(io.BytesIO(raw_bytes))
    related = document.part.related_parts
    blocks: list[dict] = []
    used_partnames: set[str] = set()
    current_heading = ""
    last_text = ""

    def emit_images(element, context: str):
        for rid in _image_rel_ids(element):
            part = related.get(rid)
            if part is None or not hasattr(part, "blob"):
                continue
            partname = str(part.partname).lstrip("/")  # "/word/media/x.png" -> zip name "word/media/x.png"
            if partname in used_partnames:
                continue
            used_partnames.add(partname)
            blocks.append(
                {
                    "kind": "image",
                    "bytes": part.blob,
                    "content_type": part.content_type,
                    "filename": partname,
                    "context": context.strip(),
                }
            )

    for item in _iter_block_items(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                level = _heading_level(item)
                if level:
                    current_heading = text
                    text = "#" * level + " " + text
                blocks.append({"kind": "paragraph", "text": text})
                last_text = item.text.strip()
            emit_images(item._p, f"{current_heading}\n{last_text}")
        elif isinstance(item, Table):
            rows = _table_rows(item)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
            emit_images(item._tbl, current_heading)

    # Media not referenced from the body (headers/footers/text boxes) — append so nothing is lost.
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        for name in sorted(n for n in zf.namelist() if n.startswith("word/media/")):
            if name in used_partnames:
                continue
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
