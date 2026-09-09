"""
llm_node.

Builds the provider chat model (per runtime config), binds the approved MCP tools
(already resolved by mcp_manager before the graph was invoked), prepends the system
prompt (+ retrieved knowledge context if any), and invokes the model.

The router (see builder.py conditional edge) inspects the returned AIMessage for
tool_calls to decide whether to go to hitl_gate, tool_exec_node, or end the turn.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

from app.graphs.llm_providers import build_chat_model
from app.graphs.state import GraphState


async def llm_node(state: GraphState) -> dict[str, Any]:
    runtime = state["runtime"]

    model = build_chat_model(
        provider=runtime.get("model_provider"),
        model=runtime.get("model_name"),
        temperature=runtime.get("model_temperature", 0.7),
    )

    bound_tools = runtime.get("bound_tools") or []
    if bound_tools:
        model = model.bind_tools(bound_tools)

    system_prompt = runtime.get("system_prompt") or "You are a helpful assistant."

    clinic_context = runtime.get("clinic_context")
    if clinic_context:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"اطلاعات کلینیکی که در حال حاضر با آن در ارتباط هستید:\n{clinic_context}"
        )

    context = state.get("retrieved_context")
    if context:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"Use the following retrieved knowledge if relevant to the user's question:\n{context}"
        )
    print(f"[RAG DEBUG] Final system_prompt sent to model (first 800 chars):\n{system_prompt[:800]}")
    print(f"[RAG DEBUG] Model provider={runtime.get('model_provider')} model={runtime.get('model_name')}")

    messages = [SystemMessage(content=system_prompt), *state["messages"]]
    ai_message = await model.ainvoke(messages)

    return {"messages": [ai_message]}