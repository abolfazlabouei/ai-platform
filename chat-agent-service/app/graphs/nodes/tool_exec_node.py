"""
tool_exec_node.

Executes every (non-rejected) pending tool_call against the corresponding MCP server
via mcp_manager.client_pool, and appends a ToolMessage per call so llm_node can
process the results on the next loop iteration.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from app.graphs.state import GraphState
from app.mcp_manager.client_pool import McpClientPool


async def tool_exec_node(state: GraphState) -> dict[str, Any]:
    last_ai_message = state["messages"][-1]
    tool_calls = getattr(last_ai_message, "tool_calls", None) or []
    rejected_ids = state.get("rejected_tool_call_ids", set())

    pool = McpClientPool()
    tool_messages: list[ToolMessage] = []
    user_id = state.get("runtime", {}).get("user_id")

    for tc in tool_calls:
        if tc["id"] in rejected_ids:
            tool_messages.append(
                ToolMessage(
                    content="User rejected this tool call. Do not retry it; ask the user how to proceed.",
                    tool_call_id=tc["id"],
                    name=tc["name"],
                )
            )
            continue

        try:
            result = await pool.call_tool(tool_name=tc["name"], arguments=tc["args"], user_id=user_id)
            tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"], name=tc["name"]))
        except Exception as exc:  # noqa: BLE001 — surfaced to the model, not swallowed silently
            tool_messages.append(
                ToolMessage(content=f"Tool call failed: {exc}", tool_call_id=tc["id"], name=tc["name"])
            )

    return {"messages": tool_messages, "rejected_tool_call_ids": set()}
