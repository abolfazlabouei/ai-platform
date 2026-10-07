"""
Proxies chat media attachments (image/audio) to file-processing-service's upload
endpoint, and resolves media_id -> presigned URL. Kept as a thin proxy so the chat
frontend only ever talks to chat-agent-service, never directly to
file-processing-service.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, UploadFile

from app.core.security import CurrentUser, require_user
from app.services.file_client import FileClient

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload")
async def upload_media(request: Request, file: UploadFile, user: CurrentUser = Depends(require_user)):
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.removeprefix("Bearer ").strip() or None
    content = await file.read()
    return await FileClient().upload_media(
        filename=file.filename, content=content, mime=file.content_type, bearer_token=bearer_token
    )


@router.get("/{media_id}")
async def get_media_url(media_id: str):
    return await FileClient().get_media_url(media_id)
