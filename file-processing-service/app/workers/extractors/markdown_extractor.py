"""
Markdown extractor. Parses into a token stream via markdown-it-py and groups
tokens into paragraph/table/heading raw blocks. Headings are kept as their own
paragraph blocks (prefixed with the same '#' markers) so text_chunker can use them
as natural split points and knowledge-service retrieval can preserve section context.
"""
from __future__ import annotations

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False}).enable("table")


def _render_table(token_stream: list, start_idx: int) -> tuple[list[list[str]], int]:
    """Consumes a markdown-it table token sequence starting at `start_idx`, returns (rows, next_idx)."""
    rows: list[list[str]] = []
    i = start_idx
    current_row: list[str] = []
    while i < len(token_stream) and token_stream[i].type != "table_close":
        tok = token_stream[i]
        if tok.type == "tr_open":
            current_row = []
        elif tok.type in ("th_open", "td_open"):
            # next token is inline content
            i += 1
            current_row.append(token_stream[i].content if i < len(token_stream) else "")
        elif tok.type == "tr_close":
            rows.append(current_row)
        i += 1
    return rows, i + 1  # skip past table_close


def extract_markdown(raw_bytes: bytes) -> list[dict]:
    text = raw_bytes.decode("utf-8", errors="replace")
    tokens = _md.parse(text)
    blocks: list[dict] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "heading_open":
            level = int(tok.tag[1])
            i += 1
            content = tokens[i].content if i < len(tokens) else ""
            blocks.append({"kind": "paragraph", "text": f"{'#' * level} {content}"})

        elif tok.type == "paragraph_open":
            i += 1
            content = tokens[i].content if i < len(tokens) else ""
            if content.strip():
                blocks.append({"kind": "paragraph", "text": content.strip()})

        elif tok.type == "table_open":
            rows, i = _render_table(tokens, i + 1)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
            continue

        elif tok.type == "fence":
            # code block — kept as its own paragraph-like block, tagged so downstream
            # chunkers/knowledge-service can choose to treat it distinctly if desired
            blocks.append({"kind": "paragraph", "text": f"```{tok.info}\n{tok.content}```"})

        i += 1

    return blocks
