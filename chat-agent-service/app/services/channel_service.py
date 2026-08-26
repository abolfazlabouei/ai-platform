"""
channel_service: resolves/creates a ChannelIdentity for gateway-originated messages,
and finds or creates the Conversation associated with it. This is the only piece a
future telegram-gateway/whatsapp-gateway service needs to call before delegating to
the normal /chat endpoints — chat_service itself stays channel-agnostic.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_identity import ChannelIdentity
from app.repositories.channel_identity_repo import ChannelIdentityRepo


class ChannelService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ChannelIdentityRepo(db)

    async def resolve_or_create_identity(
        self, channel: str, external_id: str, default_user_id: str | None = None, metadata: dict | None = None
    ) -> ChannelIdentity:
        identity = await self.repo.get_by_external_id(channel, external_id)
        if identity:
            return identity
        return await self.repo.create(
            user_id=default_user_id or f"{channel}:{external_id}",
            channel=channel,
            external_id=external_id,
            extra_metadata=metadata or {},
        )
