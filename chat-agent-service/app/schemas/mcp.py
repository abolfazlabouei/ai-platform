"""Request/response schemas for /mcp-servers CRUD, test-connection, and tool approval."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class McpServerCreate(BaseModel):
    name: str
    transport: str  # sse | streamable_http | stdio
    url: str
    auth_config: dict = {}


class McpServerOut(BaseModel):
    id: uuid.UUID
    name: str
    transport: str
    url: str
    status: str
    last_error: str | None
    last_tested_at: datetime | None
    created_at: datetime


class McpToolOut(BaseModel):
    id: uuid.UUID
    tool_name: str
    description: str | None
    input_schema: dict
    approval_status: str
    requires_hitl: bool


class ToolApprovalUpdate(BaseModel):
    approval_status: str  # approved | rejected
    requires_hitl: bool = False


class McpConnectionStatusOut(BaseModel):
    connected: bool
    status: str
    expires_at: datetime | None = None
    scopes: str | None = None
    last_error: str | None = None


class McpAuthorizeOut(BaseModel):
    authorization_url: str
