"""
The real compiled LangGraph with a scripted chat model: proves the whole progressive-disclosure
loop (catalog in the prompt -> skill_load -> skill_read_file -> answer) through llm_node,
route_after_llm and tool_exec_node, with skills carried only as plain data in RuntimeConfig.
"""
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.config import settings
from app.skills import package as pkg
from app.skills import tools as skill_tools
from app.skills.catalog import build_catalog
from app.services.skill_service import SkillService
from tests.skill_helpers import skill_md

USER = "user-1"


class ScriptedModel:
    """Replays AI messages in order and records what it was shown."""

    def __init__(self, replies):
        self.replies, self.seen, self.bound = list(replies), [], []

    def bind_tools(self, tools):
        self.bound = [t.name for t in tools]
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.replies[len(self.seen) - 1]


@pytest.fixture
async def graph(monkeypatch, session_maker, storage):
    import app.checkpointer.postgres_saver as saver
    import app.graphs.builder as builder
    from app.graphs.nodes import llm_node, tool_exec_node

    monkeypatch.setattr(settings, "USE_POSTGRES_CHECKPOINTER", False)
    monkeypatch.setattr(saver, "_checkpointer", None)
    monkeypatch.setattr(builder, "_compiled_graph_cache", None)
    monkeypatch.setattr(skill_tools, "AsyncSessionLocal", session_maker)
    for module in (llm_node, tool_exec_node):  # both nodes build tools from the same in-memory store
        monkeypatch.setattr(module, "get_internal_tools", lambda rt: skill_tools.build_skill_tools(rt, storage))

    async def noop_inline(messages):
        return messages

    monkeypatch.setattr(llm_node, "inline_media", noop_inline)
    return await builder.get_compiled_graph(), llm_node


async def attach(db, storage):
    service = SkillService(db, storage)
    package = pkg.parse_json(
        skill_md(name="monthly-report", body="# Report\nFollow references/format.md.\n",
                 description="Write the clinic monthly report. Use when the user asks for a monthly report."),
        {"references/format.md": "# Layout\nUse a table per service."},
    )
    created = await service.save_package(USER, package, update=False)
    return await service.resolve_for_runtime(USER, [{"skill_id": str(created.skill.id), "version": None}])


async def test_model_discovers_loads_reads_and_answers(graph, db, storage, monkeypatch):
    compiled, llm_node = graph
    skills = await attach(db, storage)
    model = ScriptedModel([
        AIMessage(content="", tool_calls=[{"id": "t1", "name": "skill_load", "args": {"name": "monthly-report"}}]),
        AIMessage(content="", tool_calls=[{"id": "t2", "name": "skill_read_file",
                                          "args": {"name": "monthly-report", "path": "references/format.md"}}]),
        AIMessage(content="Here is the report, one table per service."),
    ])
    monkeypatch.setattr(llm_node, "build_chat_model", lambda **kw: model)

    runtime = {
        "conversation_id": str(uuid.uuid4()), "user_id": USER, "agent_id": None, "system_prompt": "You are the secretary.",
        "skills": skills, "skills_catalog": build_catalog(skills), "tool_hitl_map": {},
    }
    config = {"configurable": {"thread_id": runtime["conversation_id"]}}
    state = await compiled.ainvoke(
        {"_incoming_blocks": [{"type": "text", "text": "گزارش ماهانه را بنویس"}], "runtime": runtime}, config=config
    )

    # level 1: the first call sees the catalog (names + descriptions), not the body
    first_system = model.seen[0][0]
    assert isinstance(first_system, SystemMessage)
    assert "- monthly-report:" in first_system.content and "Follow references/format.md" not in first_system.content
    assert {"skill_load", "skill_read_file"} <= set(model.bound)

    # level 2: the body arrives as a tool result on the next call
    tool_results = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
    assert "Follow references/format.md." in tool_results[0].content and "references/format.md (" in tool_results[0].content

    # level 3: the referenced file arrives on the call after that
    assert any("Use a table per service." in m.content for m in model.seen[2] if isinstance(m, ToolMessage))

    assert state["messages"][-1].content == "Here is the report, one table per service."
    assert isinstance(model.seen[0][1], HumanMessage)


async def test_chat_without_skills_gets_no_skill_prompt_or_tools(graph, monkeypatch):
    compiled, llm_node = graph
    model = ScriptedModel([AIMessage(content="plain answer")])
    monkeypatch.setattr(llm_node, "build_chat_model", lambda **kw: model)
    runtime = {"conversation_id": str(uuid.uuid4()), "user_id": USER, "system_prompt": "Be brief.", "skills": [],
               "skills_catalog": "", "tool_hitl_map": {}}
    await compiled.ainvoke(
        {"_incoming_blocks": [{"type": "text", "text": "hi"}], "runtime": runtime},
        config={"configurable": {"thread_id": runtime["conversation_id"]}},
    )
    assert "Skills" not in model.seen[0][0].content and not any(n.startswith("skill_") for n in model.bound)


async def test_skill_runtime_survives_checkpoint_roundtrip(graph, db, storage, monkeypatch):
    """The runtime (with plain-data skills) is checkpointed; a second turn on the same thread still works."""
    compiled, llm_node = graph
    skills = await attach(db, storage)
    model = ScriptedModel([
        AIMessage(content="first"),
        AIMessage(content="", tool_calls=[{"id": "t1", "name": "skill_load", "args": {"name": "monthly-report"}}]),
        AIMessage(content="second"),
    ])
    monkeypatch.setattr(llm_node, "build_chat_model", lambda **kw: model)
    runtime = {"conversation_id": str(uuid.uuid4()), "user_id": USER, "skills": skills,
               "skills_catalog": build_catalog(skills), "tool_hitl_map": {}}
    config = {"configurable": {"thread_id": runtime["conversation_id"]}}
    await compiled.ainvoke({"_incoming_blocks": [{"type": "text", "text": "one"}], "runtime": runtime}, config=config)
    state = await compiled.ainvoke({"_incoming_blocks": [{"type": "text", "text": "two"}], "runtime": runtime}, config=config)
    assert state["messages"][-1].content == "second"
    assert any("Follow references/format.md." in m.content for m in model.seen[2] if isinstance(m, ToolMessage))
