"""
Chat media attachments (image/audio).

POST /media/upload stores the file in chat-agent-service's own bucket and returns a
media_id to reference from an image/audio content block. GET /media/files/{key}
serves uploaded and generated media back to clients.

These are kept out of file-processing-service on purpose: that service only accepts
documents (docx/pdf/xlsx/md) and starts an extraction job for every upload.
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from app.core.config import settings
from app.core.media_types import AUDIO_FORMATS, IMAGE_MIMES, normalize_mime
from app.core.security import CurrentUser, require_user
from app.services.object_store import get_media, put_media

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload")
async def upload_media(file: UploadFile, user: CurrentUser = Depends(require_user)):
    mime = normalize_mime(file.content_type)
    if mime in IMAGE_MIMES:
        kind = "image"
    elif mime in AUDIO_FORMATS:
        kind = "audio"
    else:
        raise HTTPException(
            415,
            f"Unsupported media type '{file.content_type}'. "
            f"Images: {sorted(IMAGE_MIMES)}; audio: {sorted(AUDIO_FORMATS)}",
        )

    max_bytes = settings.MAX_MEDIA_UPLOAD_MB * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, f"File exceeds max media size of {settings.MAX_MEDIA_UPLOAD_MB}MB")
    if not content:
        raise HTTPException(400, "Empty file")

    ext = IMAGE_MIMES.get(mime) or AUDIO_FORMATS[mime]
    owner = re.sub(r"[^A-Za-z0-9_-]", "_", user.user_id)
    media_id = f"uploads/{owner}/{uuid.uuid4()}.{ext}"
    url = await put_media(media_id, content, mime)
    return {"media_id": media_id, "type": kind, "mime": mime, "url": url}


@router.get("/files/{key:path}")
async def get_media_file(key: str):
    try:
        data, mime = await get_media(key)
    except KeyError:
        raise HTTPException(404, "Media not found") from None
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})
