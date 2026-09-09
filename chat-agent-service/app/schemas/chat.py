"""Request/response schemas for /chat and /agents/{id}/chat endpoints."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from shared_schemas.content_blocks import ContentBlock


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None  # omit to start a new conversation
    content_blocks: list[ContentBlock]

    # Only meaningful for ad-hoc chat (ignored/overridable-by-admin on agent chat):
    mcp_server_ids: list[uuid.UUID] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    clinic_id: str | None = None
    


class ToolApprovalRequest(BaseModel):
    decisions: dict[str, bool]  # tool_call_id -> approve(True)/reject(False)


class ChatCompleteResponse(BaseModel):
    conversation_id: uuid.UUID
    content_blocks: list[ContentBlock]
