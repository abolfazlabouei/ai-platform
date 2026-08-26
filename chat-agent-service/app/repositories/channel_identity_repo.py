"""Async CRUD queries for ChannelIdentity."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_identity import ChannelIdentity


class ChannelIdentityRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_external_id(self, channel: str, external_id: str) -> ChannelIdentity | None:
        result = await self.db.execute(
            select(ChannelIdentity).where(
                ChannelIdentity.channel == channel, ChannelIdentity.external_id == external_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> ChannelIdentity:
        identity = ChannelIdentity(**kwargs)
        self.db.add(identity)
        await self.db.commit()
        await self.db.refresh(identity)
        return identity
