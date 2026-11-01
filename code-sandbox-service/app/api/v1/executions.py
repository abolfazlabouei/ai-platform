"""Run code inside a session's sandbox."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_service_key
from app.db.session import get_db
from app.schemas.sandbox import ExecutionCreate, ExecutionOut
from app.services.runtime import build_services

router = APIRouter(prefix="/sessions", tags=["executions"], dependencies=[Depends(require_service_key)])


@router.post("/{session_id}/executions", response_model=ExecutionOut)
async def create_execution(session_id: uuid.UUID, body: ExecutionCreate, db: AsyncSession = Depends(get_db)):
    svc = build_services(db)
    row = await svc.sessions.get(session_id)
    return await svc.executions.run(row, body.code, body.timeout_seconds)
