"""
Message ORM model. content_blocks follows the shared content-block contract:
each block is {"type": "text"|"image"|"audio"|"tool_call"|"tool_result"|"generated_image", ...}.
This table is the queryable history store; LangGraph's own checkpointer separately
persists graph state needed for resuming HITL interrupts.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"), nullable=False)

    # list[ContentBlock] — see shared_schemas.content_blocks
    content_blocks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # free-form metadata: model used, token usage, tool name for tool messages, etc.
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
