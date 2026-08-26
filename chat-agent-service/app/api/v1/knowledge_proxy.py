"""Thin proxy so the chat UI can list the user's knowledge bases (for selection in
ad-hoc chat or when building an Agent) without talking to knowledge-service directly."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import CurrentUser, require_user
from app.services.knowledge_client import KnowledgeClient

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


@router.get("")
async def list_knowledge_bases(request: Request, user: CurrentUser = Depends(require_user)):
    # require_user already validated this token against the SAME shared JWT_SECRET
    # knowledge-service uses, so forwarding it as-is lets knowledge-service
    # independently authenticate the same caller rather than trusting a passed user_id.
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.removeprefix("Bearer ").strip()
    if not bearer_token:
        raise HTTPException(401, "Missing bearer token")

    client = KnowledgeClient()
    return await client.list_knowledge_bases(bearer_token)
