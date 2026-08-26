"""Message + Conversation transport contracts shared across services."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared_schemas.content_blocks import ContentBlock

Role = Literal["user", "assistant", "system", "tool"]


class MessageIn(BaseModel):
    role: Role = "user"
    content_blocks: list[ContentBlock]


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Role
    content_blocks: list[ContentBlock]
    created_at: datetime
