"""
title_service: generates a short, human-readable conversation title from the
user's first message. Applies identically to ad-hoc chat and agent chat — the
trigger is "this conversation's title is still unset", not which mode the
conversation is in (see conversation_service.set_title_if_empty).

Uses a cheap, low-latency LLM call by default; falls back to a simple truncation
heuristic if that call fails for ANY reason (missing/invalid API key, provider
outage, rate limit, ...) so title generation can never break or block the
actual chat turn it's piggybacking on.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.graphs.llm_providers import build_chat_model

MAX_TITLE_WORDS_FALLBACK = 8
MAX_TITLE_CHARS = 100
MAX_INPUT_CHARS = 2000  # defensive cap; a title doesn't need the full message

_TITLE_SYSTEM_PROMPT = (
    "Generate a short, descriptive title (maximum 6 words) summarizing the "
    "user's message below. Do not use quotes or trailing punctuation. "
    "Respond with ONLY the title text, nothing else."
)


def _extract_text(content_blocks: list[dict]) -> str:
    """Pulls plain text out of a content_blocks list, ignoring image/audio/tool blocks."""
    parts = [b["text"] for b in content_blocks if b.get("type") == "text" and b.get("text")]
    return " ".join(parts).strip()


def _fallback_title(text: str) -> str:
    """Used when the LLM call fails — never leaves a conversation without a title."""
    words = text.split()
    if not words:
        return "New conversation"
    truncated = " ".join(words[:MAX_TITLE_WORDS_FALLBACK])
    return truncated + ("…" if len(words) > MAX_TITLE_WORDS_FALLBACK else "")


async def generate_title(content_blocks: list[dict]) -> str:
    text = _extract_text(content_blocks)
    if not text:
        # e.g. the first message was image/audio-only — nothing textual to summarize
        return "New conversation"

    try:
        model = build_chat_model(
            provider=settings.DEFAULT_MODEL_PROVIDER,
            model=settings.DEFAULT_MODEL_NAME,
            temperature=0.3,
        )
        messages = [
            SystemMessage(content=_TITLE_SYSTEM_PROMPT),
            HumanMessage(content=text[:MAX_INPUT_CHARS]),
        ]
        response = await model.ainvoke(messages)
        content = response.content
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        title = (content or "").strip().strip('"').strip("'")
        return title[:MAX_TITLE_CHARS] if title else _fallback_title(text)
    except Exception:  # noqa: BLE001 — title generation must never break the chat turn
        return _fallback_title(text)