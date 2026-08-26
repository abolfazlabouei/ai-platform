"""
AgentCard: discoverable metadata for any agent, used by the (future) multi-agent
orchestrator to build an in-memory registry via GET /agents?is_composable=true.
"""
from __future__ import annotations

from pydantic import BaseModel


class AgentCard(BaseModel):
    id: str
    name: str
    description: str | None = None
    capabilities: list[str] = []
    is_composable: bool = False
    invoke_url: str  # e.g. https://chat-agent-service/api/v1/agents/{id}/chat/complete
    stream_url: str
