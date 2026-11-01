"""
FileImportService: copies a user's uploaded platform document into the sandbox at
/workspace/inputs/<original filename>. The control plane resolves and downloads the
file itself (file-processing-service -> presigned MinIO URL); the sandbox never sees
the URL or any credential.
"""
from __future__ import annotations

import uuid

import httpx

from app.core.config import Settings, settings as default_settings
from app.sandbox.executor import ExecutionError, Executor
from app.sandbox.files import INPUTS_DIR, sanitize_filename


class FileImportService:
    def __init__(self, executor: Executor, cfg: Settings | None = None):
        self.executor = executor
        self.cfg = cfg or default_settings

    async def _download(self, file_id: str) -> tuple[str, bytes]:
        try:
            fid = str(uuid.UUID(file_id))
        except (ValueError, TypeError):
            raise ExecutionError("file_id must be a uuid") from None
        max_bytes = self.cfg.SANDBOX_MAX_IMPORT_MB * 1024 * 1024
        base = self.cfg.FILE_SERVICE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=60) as client:
            meta = await client.get(f"{base}/api/v1/files/{fid}")
            if meta.status_code == 404:
                raise ExecutionError("file not found")
            meta.raise_for_status()
            info = meta.json()
            if int(info.get("size_bytes") or 0) > max_bytes:
                raise ExecutionError(f"file is larger than {self.cfg.SANDBOX_MAX_IMPORT_MB} MB")
            link = await client.get(f"{base}/api/v1/files/{fid}/download-url")
            link.raise_for_status()
            url = link.json()["url"]

            data = bytearray()
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ExecutionError(f"file is larger than {self.cfg.SANDBOX_MAX_IMPORT_MB} MB")
        return sanitize_filename(info.get("filename") or fid), bytes(data)

    async def import_file(self, container_id: str, file_id: str) -> dict:
        filename, data = await self._download(file_id)
        path = await self.executor.write_file(container_id, f"{INPUTS_DIR}/{filename}", data)
        return {"path": path, "size": len(data), "filename": filename}
