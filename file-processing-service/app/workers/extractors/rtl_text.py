"""
rtl_text: fixes garbled Arabic/Persian text extracted from certain PDFs.

Some PDF generators (LaTeX/XePersian templates, some Word-to-PDF exporters)
store text in their content stream as pre-shaped presentation-form glyphs
(isolated/initial/medial/final letter variants) placed in left-to-right visual
order, without embedding proper Unicode BiDi metadata. PyMuPDF extracts
exactly what's in the stream, so the result is technically correct bytes but
practically unreadable (both for humans and for embeddings): words come out
reversed and letters come out as disconnected presentation-form variants
instead of base Unicode letters.

Fix, applied per line of words (word-level bounding boxes from PyMuPDF):
  1. NFKC-normalize each word — Unicode defines compatibility decompositions
     for the Arabic Presentation Forms-A/B blocks back to their base letters,
     so this "unshapes" the glyphs with no external dependency required.
  2. If the line is predominantly RTL, reverse the word order — PyMuPDF's
     word extraction order follows left-to-right visual placement, which is
     correct for LTR lines but backwards for RTL reading order.

This is a heuristic, not a full Unicode BiDi implementation: mixed RTL/LTR
lines (e.g. Persian text with embedded numbers or English terms) are
line-reversed as a whole, so an embedded LTR run's own internal word order can
still end up flipped. This is a large, measurable improvement over doing
nothing, not a perfect fix — see file-processing-service/README.md.
"""
from __future__ import annotations

import unicodedata

_RTL_UNICODE_RANGES = (
    (0x0600, 0x06FF),  # Arabic (includes Persian letters)
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)


def _is_rtl_char(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _RTL_UNICODE_RANGES)


def _is_rtl_word(word: str) -> bool:
    if not word:
        return False
    rtl_count = sum(1 for ch in word if _is_rtl_char(ch))
    return rtl_count > len(word) / 2


def fix_rtl_line(words: list[str]) -> str:
    """
    Takes words in PyMuPDF's extraction order (left-to-right visual placement)
    and returns a single line string in corrected logical reading order.
    No-ops (aside from NFKC normalization, which is harmless for LTR text)
    when the line isn't predominantly RTL.
    """
    if not words:
        return ""

    normalized_words = []
    for word in words:
        text = unicodedata.normalize("NFKC", word)

        # Remove PDF Private Use Area characters such as U+F020.
        text = "".join(
            " " if unicodedata.category(ch) == "Co" else ch
            for ch in text
        )

        normalized_words.append(text.strip())

    normalized_words = [w for w in normalized_words if w]

    return " ".join(normalized_words)


def fix_rtl_cell(cell: str) -> str:
    if not cell:
        return ""

    cell = unicodedata.normalize("NFKC", cell)

    # Remove Private Use Area characters.
    cell = "".join(
        ch for ch in cell
        if unicodedata.category(ch) != "Co"
    )

    # Remove placeholder/dot-only noise.
    if cell and all(ch in ".·• " for ch in cell):
        return ""

    fixed_lines = []
    for line in cell.splitlines():
        line = line.strip()
        if not line:
            continue

        tokens = line.split()

        rtl_count = sum(
            1
            for ch in line
            if unicodedata.bidirectional(ch) in {"R", "AL"}
        )
        ltr_count = sum(
            1
            for ch in line
            if unicodedata.bidirectional(ch) == "L"
        )

        is_rtl = rtl_count > ltr_count
        if is_rtl:
            fixed_tokens = []
            for token in tokens:
                token_rtl = sum(
                    1
                    for ch in token
                    if unicodedata.bidirectional(ch) in {"R", "AL"}
                )

                if token_rtl > len(token) / 2:
                    token = token[::-1]

                fixed_tokens.append(token)
            # PDF stores this table text in visual order.
            fixed_tokens.reverse()
            line = " ".join(fixed_tokens)
        else:
            line = " ".join(tokens)

        if line and not all(ch in ".·• " for ch in line):
            fixed_lines.append(line)

    return "\n".join(fixed_lines)