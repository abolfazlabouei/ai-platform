"""
hitl_gate node.

Sits between llm_node's tool_calls and tool_exec_node. For every pending tool_call,
checks runtime.tool_hitl_map[tool_name]. If ANY call in the batch requires human
approval, the node calls LangGraph's `interrupt()`, which pauses execution and
persists state via the checkpointer. The API layer surfaces this as an SSE event
`tool_approval_required`; the graph resumes (approved or rejected) via
POST /conversations/{id}/tool-approval, which calls graph.ainvoke(Command(resume=...)).
"""
from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.graphs.state import GraphState


async def hitl_gate(state: GraphState) -> dict[str, Any]:
    last_ai_message = state["messages"][-1]
    tool_calls = getattr(last_ai_message, "tool_calls", None) or []
    hitl_map = state["runtime"].get("tool_hitl_map", {})

    calls_needing_approval = [tc for tc in tool_calls if hitl_map.get(tc["name"])]
    if not calls_needing_approval:
        return {}

    # Pauses the graph here. The payload is what the frontend renders as the
    # approval prompt; the eventual `resume` value is a dict of {tool_call_id: bool}.
    decision: dict[str, bool] = interrupt(
        {
            "type": "tool_approval_required",
            "tool_calls": [
                {"id": tc["id"], "name": tc["name"], "arguments": tc["args"]} for tc in calls_needing_approval
            ],
        }
    )

    rejected_ids = {tc_id for tc_id, approved in decision.items() if not approved}
    return {"rejected_tool_call_ids": rejected_ids}
