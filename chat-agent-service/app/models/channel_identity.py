"""
ChannelIdentity: maps an external platform identity (telegram chat_id, whatsapp phone
number, ...) to an internal user_id. Channel gateways (future services) use this to
resolve/create the right Conversation without chat-agent-service needing to know
anything about the originating platform.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_channel_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # telegram | whatsapp | web | ...
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)  # platform chat_id / phone / etc.

    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
