"""
sub_agent_caller node — FORWARD-LOOKING HOOK, not wired into the default graph yet.

When the multi-agent-orchestrator-service exists, a supervisor graph there will call
this service's /agents/{id}/chat/complete for each sub-agent. This node is kept here,
disconnected from the default edges, as the equivalent capability *inside* a single
agent's own graph — e.g. an agent whose tool_policy references another agent by id
instead of (or in addition to) an MCP tool. Wiring this in only requires adding a
conditional edge in builder.py; no other module needs to change.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.graphs.state import GraphState


async def sub_agent_caller(state: GraphState, sub_agent_id: str, message_text: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=settings.SERVICE_NAME, timeout=60) as client:
        resp = await client.post(
            f"/api/v1/agents/{sub_agent_id}/chat/complete",
            json={"content_blocks": [{"type": "text", "text": message_text}]},
        )
        resp.raise_for_status()
        return resp.json()
