"""
Resumes a conversation's graph after it was paused by hitl_gate's interrupt().
Distinct from mcp_servers.py's tool approval (which is a one-time policy decision
made when a server is registered) — this is the per-turn "yes, actually run this
specific call right now" confirmation during a live conversation.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.session import get_db
from app.schemas.chat import ToolApprovalRequest
from app.services.chat_service import ChatService
from app.streaming.sse import to_sse

router = APIRouter(prefix="/conversations", tags=["tool-approval"])


@router.post("/{conversation_id}/tool-approval")
async def approve_tool_calls(
    conversation_id: uuid.UUID, body: ToolApprovalRequest, db: AsyncSession = Depends(get_db)
):
    chat_service = ChatService(db)
    event_stream = chat_service.resume_tool_approval(conversation_id, body.decisions)
    return StreamingResponse(to_sse(event_stream,conversation_id=str(conversation_id)), media_type="text/event-stream")
