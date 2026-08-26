"""CRUD for knowledge bases, plus listing their linked sources (files)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.schemas.knowledge_base import (
    KBSourceOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services.kb_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _to_kb_out(kb) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id, name=kb.name, description=kb.description, created_at=kb.created_at, updated_at=kb.updated_at
    )


def _to_source_out(s) -> KBSourceOut:
    return KBSourceOut(
        id=s.id,
        knowledge_base_id=s.knowledge_base_id,
        file_id=s.file_id,
        status=s.status.value,
        chunks_embedded=s.chunks_embedded,
        error=s.error,
    )


@router.post("", response_model=KnowledgeBaseOut)
async def create_kb(
    body: KnowledgeBaseCreate, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    service = KnowledgeBaseService(db)
    kb = await service.create(user_id=user.user_id, name=body.name, description=body.description)
    return _to_kb_out(kb)


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    return [_to_kb_out(kb) for kb in await service.list_for_user(user.user_id)]


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_kb(kb_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    kb = await service.get(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    return _to_kb_out(kb)


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_kb(kb_id: uuid.UUID, body: KnowledgeBaseUpdate, db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    kb = await service.get(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    kb = await service.update(kb, **body.model_dump(exclude_unset=True))
    return _to_kb_out(kb)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    kb = await service.get(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    await service.delete(kb)


@router.get("/{kb_id}/sources", response_model=list[KBSourceOut])
async def list_sources(kb_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = KnowledgeBaseService(db)
    return [_to_source_out(s) for s in await service.list_sources(kb_id)]
