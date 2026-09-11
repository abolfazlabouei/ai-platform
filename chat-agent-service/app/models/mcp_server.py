"""
McpServer: a registered MCP endpoint (SSE/HTTP/stdio transport).
McpTool: tools discovered on test-connection, cached with an approval workflow —
tools start as `pending`, the user approves/rejects each one, and can flag
`requires_hitl=True` so the graph pauses for confirmation before executing it.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class McpTransport(str, enum.Enum):
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"


class McpServerStatus(str, enum.Enum):
    UNTESTED = "untested"
    CONNECTED = "connected"
    ERROR = "error"


class ToolApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[McpTransport] = mapped_column(Enum(McpTransport, name="mcp_transport"), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)

    # auth_config shapes:
    #   {"type": "bearer", "token": "..."}                          — existing, unchanged
    #   {"type": "oauth2_per_user", "scopes": ["https://www.googleapis.com/auth/calendar"]}
    #     — new. No client secret/token lives here; those come from global settings
    #     (GOOGLE_OAUTH_CLIENT_ID/SECRET) since one Google Cloud OAuth app is shared
    #     across all McpServers of this type. Per-user tokens live in McpUserConnection.
    auth_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[McpServerStatus] = mapped_column(
        Enum(McpServerStatus, name="mcp_server_status"), default=McpServerStatus.UNTESTED, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tools: Mapped[list["McpTool"]] = relationship(back_populates="server", cascade="all, delete-orphan")


class McpTool(Base):
    __tablename__ = "mcp_tools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )

    tool_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    approval_status: Mapped[ToolApprovalStatus] = mapped_column(
        Enum(ToolApprovalStatus, name="tool_approval_status"), default=ToolApprovalStatus.PENDING, nullable=False
    )
    requires_hitl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    server: Mapped["McpServer"] = relationship(back_populates="tools")
