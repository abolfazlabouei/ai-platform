"""
Smoke test for the graph topology itself (routing logic), independent of any live
DB/LLM/MCP connections. Full integration tests (real Postgres, mocked MCP server)
belong in a separate test module once CI infra is wired up.
"""
from langchain_core.messages import AIMessage

from app.graphs.builder import _route_after_llm


def test_route_after_llm_no_tool_calls_goes_to_output_formatter():
    state = {"messages": [AIMessage(content="hello")], "runtime": {"tool_hitl_map": {}}}
    assert _route_after_llm(state) == "output_formatter"


def test_route_after_llm_with_non_hitl_tool_call_goes_to_tool_exec():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "search", "args": {}}])
    state = {"messages": [ai_msg], "runtime": {"tool_hitl_map": {"search": False}}}
    assert _route_after_llm(state) == "tool_exec_node"


def test_route_after_llm_with_hitl_tool_call_goes_to_hitl_gate():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "delete_file", "args": {}}])
    state = {"messages": [ai_msg], "runtime": {"tool_hitl_map": {"delete_file": True}}}
    assert _route_after_llm(state) == "hitl_gate"
