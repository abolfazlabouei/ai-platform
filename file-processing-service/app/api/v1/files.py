"""
File CRUD: upload (stores raw bytes + enqueues Celery extraction/chunking),
list, get metadata, delete. Also exposes GET /files/{id}/chunks, which is the
endpoint knowledge-service's ingest pipeline calls to pull processed chunks.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.repositories.chunk_repo import ChunkRepo
from app.schemas.file import ChunkOut, FileOut, FileUploadResponse
from app.services.file_service import FileService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/files", tags=["files"])


def _to_file_out(f) -> FileOut:
    return FileOut(
        id=f.id,
        filename=f.filename,
        mime=f.mime,
        file_type=f.file_type.value,
        size_bytes=f.size_bytes,
        status=f.status.value,
        error=f.error,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


@router.post("", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db)
    content = await file.read()
    file_row, job = await service.upload(user.user_id, file.filename, content, file.content_type)
    return FileUploadResponse(file=_to_file_out(file_row), job_id=job.id)


@router.get("", response_model=list[FileOut])
async def list_files(
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db)
    files = await service.list_for_user(user.user_id, limit, offset)
    return [_to_file_out(f) for f in files]


@router.get("/{file_id}", response_model=FileOut)
async def get_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = FileService(db)
    file_row = await service.get(file_id)
    if not file_row:
        raise HTTPException(404, "File not found")
    return _to_file_out(file_row)


@router.get("/{file_id}/download-url")
async def get_download_url(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Resolves a file to a time-limited presigned URL for its raw content. Used by
    chat-agent-service's media proxy (GET /media/{id}) to turn an uploaded
    attachment's media_id into a URL the LLM provider can fetch directly, without
    ever routing the raw bytes through chat-agent-service itself.
    """
    service = FileService(db)
    file_row = await service.get(file_id)
    if not file_row:
        raise HTTPException(404, "File not found")

    from app.core.config import settings
    from app.storage.object_store import presigned_url

    url = await presigned_url(settings.S3_BUCKET_RAW, file_row.storage_key)
    return {"file_id": str(file_id), "url": url, "mime": file_row.mime}


@router.delete("/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = FileService(db)
    file_row = await service.get(file_id)
    if not file_row:
        raise HTTPException(404, "File not found")
    await service.delete(file_row)


@router.get("/{file_id}/chunks", response_model=list[ChunkOut])
async def get_file_chunks(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Consumed by knowledge-service during ingest — returns chunks in document order."""
    repo = ChunkRepo(db)
    chunks = await repo.list_for_file(file_id)
    return [
        ChunkOut(
            id=c.id,
            file_id=c.file_id,
            type=c.type.value,
            content=c.content,
            storage_key=c.storage_key,
            order_index=c.order_index,
            extra_metadata=c.extra_metadata,
        )
        for c in chunks
    ]
