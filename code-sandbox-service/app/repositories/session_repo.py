"""Data access for SandboxSession — no business rules, no Docker calls."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sandbox_session import SandboxSession, SessionStatus

_ACTIVE = (SessionStatus.CREATING, SessionStatus.READY, SessionStatus.BUSY, SessionStatus.ERROR)


class SessionRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, session_id: uuid.UUID) -> SandboxSession | None:
        return await self.db.get(SandboxSession, session_id)

    async def get_active_for_conversation(self, conversation_id: str) -> SandboxSession | None:
        result = await self.db.execute(
            select(SandboxSession).where(
                SandboxSession.conversation_id == conversation_id,
                SandboxSession.status.in_(_ACTIVE),
            )
        )
        return result.scalar_one_or_none()

    async def count_active(self, user_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(SandboxSession).where(SandboxSession.status.in_(_ACTIVE))
        if user_id is not None:
            stmt = stmt.where(SandboxSession.user_id == user_id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def list_active(self) -> list[SandboxSession]:
        result = await self.db.execute(select(SandboxSession).where(SandboxSession.status.in_(_ACTIVE)))
        return list(result.scalars().all())

    async def create(self, **fields) -> SandboxSession:
        row = SandboxSession(**fields)
        self.db.add(row)
        await self.db.flush()
        return row

    async def touch(self, row: SandboxSession) -> None:
        row.last_used_at = datetime.now(timezone.utc)

    async def mark_terminated(self, row: SandboxSession, reason: str) -> None:
        row.status = SessionStatus.TERMINATED
        row.terminated_at = datetime.now(timezone.utc)
        row.terminate_reason = reason[:64]
        row.container_id = None

    async def commit(self) -> None:
        await self.db.commit()
