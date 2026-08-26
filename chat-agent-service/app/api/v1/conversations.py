"""List/get history/delete conversations. Used by the frontend to render the sidebar
and reload previous messages for both ad-hoc chats and agent chats."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.schemas.conversation import ConversationOut, MessageOut
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    convs = await service.list_for_user(user.user_id, limit, offset)
    return [
        ConversationOut(
            id=c.id,
            agent_id=c.agent_id,
            mode=c.mode.value,
            channel=c.channel.value,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in convs
    ]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: uuid.UUID, limit: int = 50, db: AsyncSession = Depends(get_db)
):
    service = ConversationService(db)
    messages = await service.get_history(conversation_id, limit)
    return [
        MessageOut(id=m.id, role=m.role.value, content_blocks=m.content_blocks, created_at=m.created_at)
        for m in messages
    ]


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = ConversationService(db)
    conv = await service.conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    await service.delete(conv)
