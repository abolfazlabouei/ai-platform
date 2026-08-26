"""
graph_builder — the single parametric LangGraph shared by both ad-hoc chat and
agent chat. The caller (chat_service / agent_service) resolves everything
request-specific (model, bound tools, hitl map, system prompt, kb ids) into a
`RuntimeConfig` dict and passes it in as part of the initial state; the graph
topology itself never changes between ad-hoc and agent mode.

Topology:

    input_normalizer --> [knowledge_retrieval?] --> llm_node
                                                        |
                                     route_after_llm ---+--- no tool_calls --> END
                                              |
                       has tool_calls needing hitl?
                        /                              \\
                     yes                                no
                      |                                  |
                 hitl_gate                          tool_exec_node
                      |                                  |
              route_after_hitl                           |
              (rejected -> tool_exec_node anyway,          |
               so the model sees the rejection)            |
                      \\____________________________________/
                                       |
                                   llm_node (loop)
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.checkpointer.postgres_saver import get_checkpointer
from app.graphs.nodes.hitl_gate import hitl_gate
from app.graphs.nodes.input_normalizer import input_normalizer
from app.graphs.nodes.knowledge_retrieval import knowledge_retrieval
from app.graphs.nodes.llm_node import llm_node
from app.graphs.nodes.output_formatter import output_formatter
from app.graphs.nodes.tool_exec_node import tool_exec_node
from app.graphs.state import GraphState


def _route_after_llm(state: GraphState) -> str:
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    if not tool_calls:
        return "output_formatter"

    hitl_map = state["runtime"].get("tool_hitl_map", {})
    if any(hitl_map.get(tc["name"]) for tc in tool_calls):
        return "hitl_gate"
    return "tool_exec_node"


def _route_after_knowledge(state: GraphState) -> str:
    # knowledge_retrieval is a no-op passthrough when no kb_ids are configured;
    # always continue to llm_node either way.
    return "llm_node"


_compiled_graph_cache: CompiledStateGraph | None = None


async def get_compiled_graph() -> CompiledStateGraph:
    """
    Returns a singleton compiled graph. The graph topology is fixed; all per-request
    variation (model, tools, prompt) flows through GraphState["runtime"], NOT through
    graph structure, so a single compiled graph instance can serve every conversation.
    """
    global _compiled_graph_cache
    if _compiled_graph_cache is not None:
        return _compiled_graph_cache

    workflow = StateGraph(GraphState)

    workflow.add_node("input_normalizer", input_normalizer)
    workflow.add_node("knowledge_retrieval", knowledge_retrieval)
    workflow.add_node("llm_node", llm_node)
    workflow.add_node("hitl_gate", hitl_gate)
    workflow.add_node("tool_exec_node", tool_exec_node)
    workflow.add_node("output_formatter", output_formatter)

    workflow.set_entry_point("input_normalizer")
    workflow.add_edge("input_normalizer", "knowledge_retrieval")
    workflow.add_conditional_edges("knowledge_retrieval", _route_after_knowledge, {"llm_node": "llm_node"})

    workflow.add_conditional_edges(
        "llm_node",
        _route_after_llm,
        {
            "hitl_gate": "hitl_gate",
            "tool_exec_node": "tool_exec_node",
            "output_formatter": "output_formatter",
        },
    )
    workflow.add_edge("hitl_gate", "tool_exec_node")
    workflow.add_edge("tool_exec_node", "llm_node")
    workflow.add_edge("output_formatter", END)

    checkpointer = await get_checkpointer()
    _compiled_graph_cache = workflow.compile(checkpointer=checkpointer)
    return _compiled_graph_cache
