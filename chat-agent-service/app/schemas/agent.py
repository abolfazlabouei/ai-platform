"""Request/response schemas for /agents CRUD."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.skill import SkillRef


class ModelConfigIn(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.7


class ToolPolicyEntry(BaseModel):
    server_id: uuid.UUID
    tool_name: str
    status: str = "approved"  # approved | rejected
    requires_hitl: bool = False


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    model_config_: ModelConfigIn = Field(default_factory=ModelConfigIn, alias="model_config")
    mcp_server_ids: list[uuid.UUID] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    skill_ids: list[SkillRef] = Field(default_factory=list)
    tool_policy: list[ToolPolicyEntry] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    is_composable: bool = False

    model_config = {"populate_by_name": True}


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_config_: ModelConfigIn | None = Field(default=None, alias="model_config")
    mcp_server_ids: list[uuid.UUID] | None = None
    knowledge_base_ids: list[str] | None = None
    skill_ids: list[SkillRef] | None = None
    tool_policy: list[ToolPolicyEntry] | None = None
    capabilities: list[str] | None = None
    is_composable: bool | None = None

    model_config = {"populate_by_name": True}


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    model_config_: dict = Field(alias="model_config")
    mcp_server_ids: list[str]
    knowledge_base_ids: list[str]
    skill_ids: list[dict] = Field(default_factory=list)
    tool_policy: list[dict]
    capabilities: list[str]
    is_composable: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
