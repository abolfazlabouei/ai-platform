"""Thin proxy so the chat UI can list the user's knowledge bases (for selection in
ad-hoc chat or when building an Agent) without talking to knowledge-service directly."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.security import CurrentUser, require_user
from app.services.knowledge_client import KnowledgeClient

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


@router.get("")
async def list_knowledge_bases(request: Request, user: CurrentUser = Depends(require_user)):
    # Forward the caller's token if there is one (knowledge-service authenticates
    # it independently). With AUTH_DISABLED, a missing token is fine — both
    # services then fall back to the same AUTH_DISABLED_USER_ID.
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.removeprefix("Bearer ").strip() or None
    return await KnowledgeClient().list_knowledge_bases(bearer_token)
