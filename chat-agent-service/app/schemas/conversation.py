"""Request/response schemas for /conversations."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from shared_schemas.content_blocks import ContentBlock


class ConversationOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    mode: str
    channel: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content_blocks: list[ContentBlock]
    created_at: datetime
