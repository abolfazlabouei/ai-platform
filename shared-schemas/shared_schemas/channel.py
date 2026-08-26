"""ChannelIdentity transport contract — shape shared between gateways and chat-agent-service."""
from __future__ import annotations

from pydantic import BaseModel


class ChannelIdentityIn(BaseModel):
    channel: str  # telegram | whatsapp | web
    external_id: str
    extra_metadata: dict = {}


class ChannelIdentityOut(ChannelIdentityIn):
    id: str
    user_id: str
