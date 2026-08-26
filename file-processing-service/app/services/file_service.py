"""
file_service: upload handling (store raw bytes, create File+Job rows, enqueue the
Celery task) and delete (DB row + object storage cleanup, including any extracted
image chunks' storage keys).
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chunk import ChunkType
from app.models.file import File, FileStatus, FileType
from app.models.job import Job, JobStage
from app.repositories.chunk_repo import ChunkRepo
from app.repositories.file_repo import FileRepo
from app.repositories.job_repo import JobRepo
from app.storage.object_store import delete_object, put_object

_EXTENSION_TO_TYPE = {
    "docx": FileType.DOCX,
    "pdf": FileType.PDF,
    "xlsx": FileType.XLSX,
    "xlsm": FileType.XLSX,
    "md": FileType.MARKDOWN,
    "markdown": FileType.MARKDOWN,
}


def _infer_file_type(filename: str) -> FileType:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXTENSION_TO_TYPE.get(ext, FileType.UNKNOWN)


class FileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_repo = FileRepo(db)
        self.job_repo = JobRepo(db)
        self.chunk_repo = ChunkRepo(db)

    async def upload(self, user_id: str, filename: str, content: bytes, mime: str | None) -> tuple[File, Job]:
        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.MAX_UPLOAD_SIZE_MB:
            raise HTTPException(413, f"File exceeds max upload size of {settings.MAX_UPLOAD_SIZE_MB}MB")

        file_type = _infer_file_type(filename)
        if file_type == FileType.UNKNOWN:
            raise HTTPException(415, f"Unsupported file type for '{filename}'. Supported: docx, pdf, xlsx, md")

        storage_key = f"{user_id}/{uuid.uuid4()}_{filename}"
        await put_object(settings.S3_BUCKET_RAW, storage_key, content, mime)

        file_row = await self.file_repo.create(
            user_id=user_id,
            filename=filename,
            mime=mime,
            file_type=file_type,
            size_bytes=len(content),
            storage_key=storage_key,
            status=FileStatus.UPLOADED,
        )
        job = await self.job_repo.create(file_id=file_row.id, stage=JobStage.QUEUED)

        # Enqueue the Celery task; imported lazily so importing file_service never
        # requires a broker connection (e.g. when only running the API in a test).
        from app.workers.tasks import process_file

        process_file.delay(str(file_row.id), str(job.id))

        return file_row, job

    async def get(self, file_id: uuid.UUID) -> File | None:
        return await self.file_repo.get(file_id)

    async def list_for_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[File]:
        return await self.file_repo.list_for_user(user_id, limit, offset)

    async def delete(self, file_row: File) -> None:
        chunks = await self.chunk_repo.list_for_file(file_row.id)
        for chunk in chunks:
            if chunk.type == ChunkType.IMAGE and chunk.storage_key:
                await delete_object(settings.S3_BUCKET_IMAGES, chunk.storage_key)
        await delete_object(settings.S3_BUCKET_RAW, file_row.storage_key)
        await self.file_repo.delete(file_row)  # cascades to chunks/jobs via FK ondelete
