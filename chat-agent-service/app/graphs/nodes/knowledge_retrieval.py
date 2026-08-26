"""
knowledge_retrieval node.

Only runs when the request (ad-hoc or agent) has knowledge_base_ids selected.
Calls knowledge-service's /search endpoint and injects the retrieved passages into
state["retrieved_context"], which llm_node folds into the system/context message.
"""
from __future__ import annotations

from typing import Any

from app.graphs.state import GraphState
from app.services.knowledge_client import KnowledgeClient


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.type == "human":
            if isinstance(msg.content, str):
                return msg.content
            for part in msg.content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part["text"]
    return ""


async def knowledge_retrieval(state: GraphState) -> dict[str, Any]:
    kb_ids = state["runtime"].get("knowledge_base_ids") or []
    print(f"[RAG DEBUG] kb_ids from runtime config: {kb_ids}")
    if not kb_ids:
        print("[RAG DEBUG] No kb_ids configured — skipping retrieval entirely.")
        return {}

    query = _last_user_text(state)
    print(f"[RAG DEBUG] Extracted query text: {query!r}")
    if not query:
        print("[RAG DEBUG] No query text extracted from last human message — skipping retrieval.")
        return {}

    client = KnowledgeClient()
    results = await client.search(kb_ids=kb_ids, query=query, top_k=6)
    print(f"[RAG DEBUG] knowledge-service returned {len(results)} result(s)")
    for i, r in enumerate(results):
        print(f"[RAG DEBUG]   result[{i}] score={r.get('score')} content preview={r.get('content', '')[:120]!r}")

    if not results:
        return {"retrieved_context": None}

    formatted = "\n\n".join(
        f"[Source: {r.get('file_id')} / chunk {r.get('chunk_id')}]\n{r.get('content')}" for r in results
    )
    print(f"[RAG DEBUG] Final retrieved_context length: {len(formatted)} chars")
    print(f"[RAG DEBUG] retrieved_context preview (first 500 chars):\n{formatted[:500]}")
    return {"retrieved_context": formatted}