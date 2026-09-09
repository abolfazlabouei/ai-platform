"""
GraphState: the single state object threaded through every node in the LangGraph.
Kept as a TypedDict (LangGraph's preferred shape) with `messages` using the
`add_messages` reducer so nodes can just return new messages to append.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class RuntimeConfig(TypedDict, total=False):
    """Everything that varies per-request: which agent (if any), model, tools, kbs."""
    conversation_id: str
    user_id: str
    agent_id: str | None
    model_provider: str
    model_name: str
    model_temperature: float
    system_prompt: str
    knowledge_base_ids: list[str]
    bound_tools: list[Any]
    tool_hitl_map: dict[str, bool]
    clinic_context: str


class GraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    retrieved_context: str | None
    pending_tool_calls: list[dict]
    generated_images: list[dict]
    runtime: RuntimeConfig
    # Set by chat_service before invoking the graph; consumed (and effectively
    # "cleared") by input_normalizer on the first node of each turn.
    # CRITICAL: any key the graph reads/writes MUST be declared here — LangGraph
    # silently strips keys not present in this TypedDict schema from both the
    # initial input and every node's returned update. Forgetting to declare a
    # key here means it never reaches the node that expects it, with no error
    # raised anywhere (this is exactly what happened to this key previously).
    _incoming_blocks: list[dict]
    # Set by hitl_gate after interrupt() resumes with the user's approve/reject
    # decisions; consumed by tool_exec_node to skip executing rejected calls.
    rejected_tool_call_ids: set[str]