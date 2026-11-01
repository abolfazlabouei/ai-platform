"""
Internal (non-MCP) tools bound per request. Today these are the skill tools
(skill_load / skill_read_file / skill_run_script), built from plain data in
RuntimeConfig so they survive checkpoint/resume — see app/skills/tools.py.

llm_node binds their schemas; tool_exec_node dispatches a call here when its name is
in this map and falls back to the MCP pool otherwise. Names are prefixed (skill_*),
so they cannot collide with MCP tool names.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from app.skills.tools import build_skill_tools


def get_internal_tools(runtime: dict[str, Any] | None) -> dict[str, BaseTool]:
    if not runtime:
        return {}
    return dict(build_skill_tools(runtime))
