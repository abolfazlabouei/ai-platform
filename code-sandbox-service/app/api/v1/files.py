"""Workspace files: list, write text, read text, import a platform document."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_service_key
from app.db.session import get_db
from app.schemas.sandbox import (
    FileContent, FileEntry, FileWrite, ImportCreate, ImportOut, SkillImportCreate, SkillImportOut,
)
from app.services import workspace_service
from app.services.runtime import build_services

router = APIRouter(prefix="/sessions", tags=["files"], dependencies=[Depends(require_service_key)])


@router.get("/{session_id}/files", response_model=list[FileEntry])
async def list_files(session_id: uuid.UUID, path: str = Query("."), db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    return await workspace_service.list_dir(svc, await svc.sessions.get(session_id), path)


@router.put("/{session_id}/files", response_model=FileEntry)
async def write_file(session_id: uuid.UUID, body: FileWrite, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    target = await workspace_service.write_text(svc, await svc.sessions.get(session_id), body.path, body.content)
    return FileEntry(path=target, type="file", size=len(body.content.encode("utf-8")), mtime=0)


@router.get("/{session_id}/files/content", response_model=FileContent)
async def read_file(session_id: uuid.UUID, path: str = Query(...), db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    resolved, text, truncated = await workspace_service.read_text(svc, await svc.sessions.get(session_id), path)
    return FileContent(path=resolved, content=text, truncated=truncated)


@router.post("/{session_id}/imports", response_model=ImportOut)
async def import_document(session_id: uuid.UUID, body: ImportCreate, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    return await workspace_service.import_document(svc, await svc.sessions.get(session_id), body.file_id)


@router.post("/{session_id}/imports/skill", response_model=SkillImportOut)
async def import_skill(session_id: uuid.UUID, body: SkillImportCreate, db: AsyncSession = Depends(get_db)):
    """Used by chat-agent-service to place an agent skill's files in /workspace/skills/<name>/ so its scripts can
    run. The sandbox never gets object-storage credentials: the caller sends the bytes."""
    svc = build_services(db)
    row = await svc.sessions.get(session_id)
    return await workspace_service.import_skill(svc, row, body.name, [(f.path, f.content_base64) for f in body.files])
