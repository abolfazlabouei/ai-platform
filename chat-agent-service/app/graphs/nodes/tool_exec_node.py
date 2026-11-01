"""
tool_exec_node.

Executes every (non-rejected) pending tool_call against the corresponding MCP server
via mcp_manager.client_pool — or locally for built-in tools (generate_image) — and
appends a ToolMessage per call so llm_node can process the results on the next loop
iteration. Generated images are accumulated in state["generated_images"] for the turn.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from app.graphs.state import GraphState
from app.graphs.tools.image_tools import GENERATE_IMAGE_TOOL
from app.internal_tools.registry import get_internal_tools
from app.mcp_manager.client_pool import McpClientPool
from app.services.image_generation import generate_image


async def tool_exec_node(state: GraphState) -> dict[str, Any]:
    last_ai_message = state["messages"][-1]
    tool_calls = getattr(last_ai_message, "tool_calls", None) or []
    rejected_ids = state.get("rejected_tool_call_ids", set())

    pool = McpClientPool()
    internal_tools = get_internal_tools(state.get("runtime"))
    tool_messages: list[ToolMessage] = []
    generated_images = list(state.get("generated_images") or [])

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

        if tc["name"] == GENERATE_IMAGE_TOOL:
            try:
                images = await generate_image(
                    prompt=tc["args"].get("prompt", ""),
                    reference_media_ids=tc["args"].get("reference_media_ids") or [],
                )
                generated_images.extend(images)
                ids = ", ".join(img["media_id"] for img in images)
                content = f"Image generated and already shown to the user (media_id={ids}). Do not repeat the URL."
            except Exception as exc:  # noqa: BLE001 — surfaced to the model
                content = f"Image generation failed: {exc}"
            tool_messages.append(ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"]))
            continue

        if tc["name"] in internal_tools:  # skill tools: not MCP, run in-process
            try:
                result = await internal_tools[tc["name"]].ainvoke(tc["args"])
                tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"], name=tc["name"]))
            except Exception as exc:  # noqa: BLE001 — surfaced to the model
                tool_messages.append(
                    ToolMessage(content=f"Tool call failed: {exc}", tool_call_id=tc["id"], name=tc["name"])
                )
            continue

        try:
            runtime = state.get("runtime") or {}
            result = await pool.call_tool(
                tool_name=tc["name"],
                arguments=tc["args"],
                conversation_id=runtime.get("conversation_id"),
                user_id=runtime.get("user_id"),
            )
            tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"], name=tc["name"]))
        except Exception as exc:  # noqa: BLE001 — surfaced to the model, not swallowed silently
            tool_messages.append(
                ToolMessage(content=f"Tool call failed: {exc}", tool_call_id=tc["id"], name=tc["name"])
            )

    return {
        "messages": tool_messages,
        "rejected_tool_call_ids": set(),
        "generated_images": generated_images,
    }
