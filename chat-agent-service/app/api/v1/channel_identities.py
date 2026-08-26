"""
CRUD/lookup for ChannelIdentity — used by future gateways (telegram/whatsapp) to
resolve or create the mapping between a platform identity and an internal user,
before delegating to the normal chat endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from shared_schemas.channel import ChannelIdentityIn, ChannelIdentityOut
from app.services.channel_service import ChannelService

router = APIRouter(prefix="/channel-identities", tags=["channel-identities"])


@router.post("/resolve", response_model=ChannelIdentityOut)
async def resolve_identity(body: ChannelIdentityIn, db: AsyncSession = Depends(get_db)):
    service = ChannelService(db)
    identity = await service.resolve_or_create_identity(
        channel=body.channel, external_id=body.external_id, metadata=body.extra_metadata
    )
    return ChannelIdentityOut(
        id=str(identity.id),
        user_id=identity.user_id,
        channel=identity.channel,
        external_id=identity.external_id,
        extra_metadata=identity.extra_metadata,
    )
