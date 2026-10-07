"""Typed HTTP client wrapper for file-processing-service (chat media attachments)."""
from __future__ import annotations

import httpx

from app.core.config import settings


class FileClient:
    def __init__(self):
        self.base_url = settings.FILE_SERVICE_URL

    async def get_media_url(self, media_id: str) -> dict:
        """Calls file-processing-service's presigned-URL endpoint. No auth is forwarded
        here since resolving a media_id to a URL is not itself a mutating/sensitive
        action; upload, by contrast, does forward the caller's token (see upload_media)."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(f"/api/v1/files/{media_id}/download-url")
            resp.raise_for_status()
            return resp.json()

    async def upload_media(self, filename: str, content: bytes, mime: str, bearer_token: str | None = None) -> dict:
        """file-processing-service's POST /files requires an authenticated user (it
        records ownership via user_id), so the caller's bearer token is forwarded
        as-is rather than re-authenticating some other way."""
        headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
        # generous timeout: uploads can be up to MAX_UPLOAD_SIZE_MB (200MB)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=600) as client:
            files = {"file": (filename, content, mime)}
            resp = await client.post("/api/v1/files", files=files, headers=headers)
            resp.raise_for_status()
            return resp.json()
