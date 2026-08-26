"""
Ad-hoc chat endpoints — no Agent involved. The caller selects mcp_server_ids and
knowledge_base_ids per-request (per-conversation via runtime_config on first turn).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.schemas.chat import ChatCompleteResponse, ChatRequest
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.streaming.sse import to_sse

router = APIRouter(prefix="/chat", tags=["chat"])


async def _prepare_conversation(req: ChatRequest, user: CurrentUser, db: AsyncSession) -> uuid.UUID:
    conv_service = ConversationService(db)
    conv = await conv_service.get_or_create(
        conversation_id=req.conversation_id,
        user_id=user.user_id,
        agent_id=None,
        mode="ad_hoc",
        channel="api",
        runtime_config={
            "mcp_server_ids": [str(i) for i in req.mcp_server_ids],
            "knowledge_base_ids": req.knowledge_base_ids,
        },
    )
    return conv.id


@router.post("/stream")
async def chat_stream(
    req: ChatRequest, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    conversation_id = await _prepare_conversation(req, user, db)
    chat_service = ChatService(db)

    event_stream = chat_service.run_turn(
        conversation_id=conversation_id,
        user_id=user.user_id,
        content_blocks=[b.model_dump() for b in req.content_blocks],
        agent=None,
        mcp_server_ids=[str(i) for i in req.mcp_server_ids],
        knowledge_base_ids=req.knowledge_base_ids,
        model_provider=req.model_provider,
        model_name=req.model_name,
    )
    return StreamingResponse(to_sse(event_stream, conversation_id=str(conversation_id)), media_type="text/event-stream")


@router.post("/complete", response_model=ChatCompleteResponse)
async def chat_complete(
    req: ChatRequest, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    conversation_id = await _prepare_conversation(req, user, db)
    chat_service = ChatService(db)

    event_stream = chat_service.run_turn(
        conversation_id=conversation_id,
        user_id=user.user_id,
        content_blocks=[b.model_dump() for b in req.content_blocks],
        agent=None,
        mcp_server_ids=[str(i) for i in req.mcp_server_ids],
        knowledge_base_ids=req.knowledge_base_ids,
        model_provider=req.model_provider,
        model_name=req.model_name,
    )
    async for _ in event_stream:
        pass  # drain — chat_service persists the assistant message as a side effect

    conv_service = ConversationService(db)
    history = await conv_service.get_history(conversation_id, limit=1)
    last = history[-1] if history else None
    return ChatCompleteResponse(
        conversation_id=conversation_id, content_blocks=last.content_blocks if last else []
    )
