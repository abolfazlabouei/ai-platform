"""
Agent ORM model. An Agent bundles: a system prompt, a model config, a set of MCP servers,
a set of knowledge bases, and a per-tool approval/HITL policy.

`description`, `capabilities`, and `is_composable` exist specifically so a future
multi-agent-orchestrator-service can discover and call this agent as a sub-agent
(GET /agents?is_composable=true acts as a lightweight agent registry).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # {"provider": "anthropic"|"openai"|..., "model": "...", "temperature": 0.7, ...}
    model_config_json: Mapped[dict] = mapped_column("model_config", JSON, default=dict, nullable=False)

    mcp_server_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    knowledge_base_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # [{"server_id": "...", "tool_name": "...", "status": "approved|rejected", "requires_hitl": bool}]
    tool_policy: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # --- multi-agent-readiness metadata (see ARCHITECTURE.md section 6) ---
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_composable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent")
