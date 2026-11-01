"""Session lifecycle: get-or-create per conversation, inspect, reset, terminate."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_service_key
from app.db.session import get_db
from app.models.sandbox_session import SandboxSession
from app.schemas.sandbox import SessionCreate, SessionOut
from app.services.runtime import build_services

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_service_key)])


def to_session_out(row: SandboxSession) -> SessionOut:
    return SessionOut(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        language=row.language,
        status=row.status.value,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        terminated_at=row.terminated_at,
        terminate_reason=row.terminate_reason,
    )


@router.post("", response_model=SessionOut)
async def get_or_create_session(body: SessionCreate, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    row = await svc.sessions.get_or_create(body.conversation_id, body.user_id, body.language)
    await db.refresh(row)
    return to_session_out(row)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return to_session_out(await build_services(db).sessions.get(session_id))


@router.post("/{session_id}/reset", response_model=SessionOut)
async def reset_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    row = await svc.sessions.reset(await svc.sessions.get(session_id))
    await db.refresh(row)
    return to_session_out(row)


@router.delete("/{session_id}", status_code=204)
async def terminate_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    await svc.sessions.terminate(await svc.sessions.get(session_id), "api_delete")
