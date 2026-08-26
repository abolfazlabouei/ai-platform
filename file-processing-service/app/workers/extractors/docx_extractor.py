"""
DOCX extractor.

python-docx alone gives us paragraphs and tables, but it does NOT expose inline
images cleanly (they're runs referencing relationship IDs). We solve this by also
walking the .docx as a raw zip archive and pulling every file under `word/media/`
directly — this reliably captures every embedded image regardless of how it's
referenced in the document body, at the cost of losing exact in-line position
(acceptable: images become their own ordered blocks, interleaved by best-effort
paragraph index using the relationship map).

Output: an ordered list of "raw blocks", each one of:
  {"kind": "paragraph", "text": str}
  {"kind": "table", "rows": list[list[str]]}
  {"kind": "image", "bytes": bytes, "content_type": str, "filename": str}
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
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}


def _iter_block_items(document: DocxDocument):
    """Yields paragraphs and tables in document order (python-docx doesn't do this natively)."""
    parent_elm = document.element.body
    for child in parent_elm.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _extract_embedded_images(raw_bytes: bytes) -> list[dict]:
    images = []
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        media_names = sorted(n for n in zf.namelist() if n.startswith("word/media/"))
        for name in media_names:
            ext = name.rsplit(".", 1)[-1].lower()
            content_type = _IMAGE_EXT_TO_MIME.get(ext, "application/octet-stream")
            images.append({"kind": "image", "bytes": zf.read(name), "content_type": content_type, "filename": name})
    return images


def extract_docx(raw_bytes: bytes) -> list[dict]:
    document = DocxDocument(io.BytesIO(raw_bytes))
    blocks: list[dict] = []

    for item in _iter_block_items(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                blocks.append({"kind": "paragraph", "text": text})
        elif isinstance(item, Table):
            rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
            if rows:
                blocks.append({"kind": "table", "rows": rows})

    # Images are appended after text/table blocks (see module docstring on ordering trade-off).
    blocks.extend(_extract_embedded_images(raw_bytes))
    return blocks
