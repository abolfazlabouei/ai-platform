"""
Text normalization shared by ingest (workers/embed_tasks.py) and query time
(api/v1/search.py, repositories/kb_chunk_repo.py), so both sides of a match
see the same characters.

Why this exists: Persian text arrives in two spellings of several letters.
Older Iranian PDFs (and Arabic-keyboard input) use Arabic Yeh/Kaf
(U+064A / U+0643), while a Persian keyboard types Persian Yeh/Keheh
(U+06CC / U+06A9). To a text index or an embedding model these are different
characters, so a query typed on a Persian keyboard silently fails to match the
same word extracted from the PDF.
"""
from __future__ import annotations

import re
import unicodedata

_CHAR_MAP = {
    "\u064A": "\u06CC",  # Arabic Yeh -> Persian Yeh
    "\u0649": "\u06CC",  # Alef Maksura -> Persian Yeh
    "\u0643": "\u06A9",  # Arabic Kaf -> Persian Keheh
    "\u0629": "\u0647",  # Teh Marbuta -> Heh
    "\u06C0": "\u0647",  # Heh with Yeh above -> Heh
    "\u200C": " ",       # ZWNJ -> space (both sides tokenize the same way)
    "\u200F": "",        # RTL mark
    "\u200E": "",        # LTR mark
    "\u0640": "",        # Tatweel
}
# Arabic-Indic (U+0660-0669) and Persian (U+06F0-06F9) digits -> ASCII digits
_CHAR_MAP.update({chr(0x0660 + i): str(i) for i in range(10)})
_CHAR_MAP.update({chr(0x06F0 + i): str(i) for i in range(10)})
_TRANSLATION = str.maketrans(_CHAR_MAP)

_DIACRITICS = re.compile("[\u064B-\u065F\u0670]")  # harakat + superscript alef
_WORD = re.compile(r"\w+")

_TOC_SECTION_RE = re.compile(
    r"(?<!\w)\d{1,2}\s*[-–—]\s*\d{1,2}(?!\w)"
)

_TOC_LABELS = (
    "فهرست مطالب",
    "فهرست مندرجات",
    "table of contents",
)

# Very common Persian function words. With OR-style lexical matching (see
# query_terms) these would match nearly every chunk and drown out the
# content words, because ts_rank_cd has no IDF weighting.
PERSIAN_STOPWORDS = frozenset(
    """
    و در به از که این آن را با برای است هست بود باشد باید دارد دارند می نمی
    چه چی چیزی چیست کدام چگونه چرا آیا یک تا یا هر هم بر نیز شود شد شده
    کند کنند کرد کرده های هایی ها ای او ما شما ان همه بین بعد قبل اگر ولی اما
    """.split()
)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANSLATION)
    text = _DIACRITICS.sub("", text)
    return text


def query_terms(query: str) -> list[str]:
    """Normalized, de-duplicated content words from a natural-language query,
    with stopwords and 1-character tokens removed."""
    seen: set[str] = set()
    terms: list[str] = []
    for token in _WORD.findall(normalize_text(query).lower()):
        if len(token) < 2 or token in PERSIAN_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def bm25_tokens(text: str | None) -> list[str]:
    """Normalize and tokenize Persian text for BM25.

    Unlike query_terms(), this function preserves repeated terms
    and does not remove stopwords, so BM25 can use term frequency
    and corpus-level inverse document frequency.
    """
    if not text:
        return []

    return _WORD.findall(normalize_text(text).lower())


def has_enough_text(text: str | None, min_word_chars: int = 15) -> bool:
    """False for chunks that are essentially empty after extraction. They carry no retrievable meaning but still
    get embedded and can show up as nonsense search hits."""
    return len(re.findall(r"\w", text or "")) >= min_word_chars


def is_likely_toc(text: str | None) -> bool:
    """Conservatively detect table-of-contents chunks."""
    normalized = normalize_text(text or "").lower()

    # Explicit table-of-contents labels
    if any(label in normalized for label in _TOC_LABELS):
        return True

    lines = [
        line.strip()
        for line in normalized.splitlines()
        if line.strip()
    ]

    if len(lines) < 25:
        return False

    page_number_lines = sum(
        bool(re.fullmatch(r"\d{1,3}", line))
        for line in lines
    )

    section_count = len(_TOC_SECTION_RE.findall(normalized))
    chapter_count = len(
        re.findall(
            r"فصل\s+(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|\d{1,2})",
            normalized,
        )
    )

    page_number_ratio = page_number_lines / len(lines)
    return (
        page_number_lines >= 8
        and page_number_ratio >= 0.28
        and section_count >= 4
        and chapter_count >= 2
    )
