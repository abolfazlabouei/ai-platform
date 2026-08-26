"""Conversation ORM model. id doubles as the LangGraph checkpointer thread_id."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ConversationMode(str, enum.Enum):
    AD_HOC = "ad_hoc"
    AGENT = "agent"


class ConversationChannel(str, enum.Enum):
    WEB = "web"
    API = "api"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    ORCHESTRATOR = "orchestrator"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[ConversationMode] = mapped_column(
        Enum(ConversationMode, name="conversation_mode"), default=ConversationMode.AD_HOC, nullable=False
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(ConversationChannel, name="conversation_channel"), default=ConversationChannel.WEB, nullable=False
    )
    channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_identities.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # ad-hoc runtime selections: {"mcp_server_ids": [...], "knowledge_base_ids": [...], "model": {...}}
    runtime_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    agent: Mapped["Agent | None"] = relationship(back_populates="conversations")
