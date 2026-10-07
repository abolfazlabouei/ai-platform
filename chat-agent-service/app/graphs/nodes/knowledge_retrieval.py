"""
knowledge_retrieval node.

Only runs when the request (ad-hoc or agent) has knowledge_base_ids selected.
Calls knowledge-service's /search endpoint and stores the formatted passages in
state["retrieved_context"], which llm_node folds into the system message.

state["retrieved_context"] semantics (read by llm_node):
  None  -> no knowledge base on this request: answer normally
  ""    -> knowledge base searched, nothing relevant found: say so, don't guess
  str   -> numbered sources to answer from

Follow-up questions ("و قیمتش چقدره؟") are rewritten into standalone search queries
from the recent conversation (settings.RAG_QUERY_REWRITE) — embedding the raw
follow-up alone retrieves the wrong chunks.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.graphs.llm_providers import build_chat_model
from app.graphs.state import GraphState
from app.services.knowledge_client import KnowledgeClient

logger = logging.getLogger(__name__)

_TYPE_LABELS = {"text": "متن", "table": "جدول", "image": "تصویر"}

_REWRITE_PROMPT = (
    "You rewrite the user's LAST message into a standalone search query for a document "
    "search engine, using the conversation only to resolve references (it, that, its price, "
    "the second one...). Keep the user's language and all names, numbers and key terms. "
    "If the last message is already standalone, return it unchanged. "
    "Output ONLY the query text — no quotes, no explanation."
)


def _debug(msg: str) -> None:
    if settings.RAG_DEBUG:
        print(f"[RAG DEBUG] {msg}")


def _message_text(msg) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return " ".join(p.get("text", "") for p in msg.content if isinstance(p, dict) and p.get("type") == "text")


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.type == "human":
            return _message_text(msg).strip()
    return ""


async def _standalone_query(state: GraphState, question: str) -> str:
    """Rewrites a follow-up into a standalone query; returns `question` on any problem."""
    messages = state.get("messages", [])
    history = [m for m in messages[:-1] if m.type in ("human", "ai") and _message_text(m).strip()]
    if not settings.RAG_QUERY_REWRITE or not any(m.type == "human" for m in history):
        return question  # first turn: nothing to resolve

    transcript = "\n".join(
        f"{'User' if m.type == 'human' else 'Assistant'}: {_message_text(m).strip()[:600]}" for m in history[-6:]
    )
    runtime = state["runtime"]
    try:
        model = build_chat_model(
            provider=runtime.get("model_provider"), model=runtime.get("model_name"), temperature=0
        )
        result = await model.ainvoke(
            [
                SystemMessage(content=_REWRITE_PROMPT),
                HumanMessage(content=f"Conversation:\n{transcript}\n\nLast message: {question}"),
            ]
        )
        rewritten = _message_text(result).strip().strip('"').strip("«»").strip()
        # sanity bounds: an empty or essay-length "query" means the model misbehaved
        if 0 < len(rewritten) <= max(300, 3 * len(question)):
            return rewritten
    except Exception as exc:  # noqa: BLE001
        logger.warning("query rewrite failed, using raw question: %s", exc)
    return question


def _format_sources(results: list[dict]) -> str:
    parts: list[str] = []
    used = 0
    for i, r in enumerate(results, start=1):
        content = (r.get("content") or "").strip()
        if not content:
            continue
        label = _TYPE_LABELS.get(r.get("type") or "", "متن")
        block = f"<منبع شماره={i} نوع={label}>\n{content}\n</منبع>"
        if used + len(block) > settings.RAG_MAX_CONTEXT_CHARS and parts:
            break  # keep the highest-scoring sources that fit the prompt budget
        if len(block) > settings.RAG_MAX_CONTEXT_CHARS:  # single oversized chunk
            block = block[: settings.RAG_MAX_CONTEXT_CHARS] + "\n…\n</منبع>"
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


async def knowledge_retrieval(state: GraphState) -> dict[str, Any]:
    kb_ids = state["runtime"].get("knowledge_base_ids") or []
    if not kb_ids:
        # explicit None so context from an earlier turn (checkpointed state) never leaks in
        return {"retrieved_context": None}

    question = _last_user_text(state)
    if not question:
        return {"retrieved_context": None}

    query = await _standalone_query(state, question)
    _debug(f"kb_ids={kb_ids} question={question!r} search_query={query!r}")

    try:
        results = await KnowledgeClient().search(kb_ids=kb_ids, query=query, top_k=settings.RAG_TOP_K)
    except Exception as exc:  # noqa: BLE001 — knowledge-service down: answer, but don't crash the turn
        logger.error("knowledge search failed: %s", exc)
        _debug(f"search FAILED: {exc}")
        return {"retrieved_context": ""}

    _debug(f"{len(results)} result(s)")
    for i, r in enumerate(results, start=1):
        preview = (r.get("content") or "").replace("\n", " ")[:120]
        _debug(f"  #{i} score={r.get('score'):.3f} type={r.get('type')} {preview!r}")

    formatted = _format_sources(results) if results else ""
    _debug(f"context chars={len(formatted)}")
    return {"retrieved_context": formatted}
