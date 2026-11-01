"""
SessionService: session lifecycle — get-or-create per conversation, transparent
replacement of dead containers, reset, terminate. Enforces the global and per-user
session caps: over the cap is a clear error, never silent eviction of someone
else's session.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings as default_settings
from app.models.sandbox_session import SandboxSession, SessionStatus
from app.repositories.session_repo import SessionRepo
from app.sandbox.docker_backend import DockerBackend
from app.sandbox.warm_pool import WarmPool

log = logging.getLogger(__name__)


class CapacityError(Exception):
    """Global or per-user session cap reached (HTTP 429 / tool error)."""


class SessionNotFound(Exception):
    pass


@dataclass
class ContainerHandle:
    container_id: str
    workspace_reset: bool  # True when a dead container was replaced (workspace is empty again)


def image_for(language: str, cfg: Settings) -> str:
    if language == "python":
        return cfg.SANDBOX_IMAGE_PYTHON
    raise ValueError(f"unsupported language '{language}'")


class SessionService:
    def __init__(self, db: AsyncSession, backend: DockerBackend, pool: WarmPool, cfg: Settings | None = None):
        self.db = db
        self.repo = SessionRepo(db)
        self.backend = backend
        self.pool = pool
        self.cfg = cfg or default_settings

    async def _acquire_container(self, image: str, session_id: str) -> str:
        container_id = await self.pool.claim(image)
        if container_id is None:
            container_id = await self.pool.create_container(image, session_id=session_id)
        self.pool.refill_in_background(image)
        return container_id

    async def _check_caps(self, user_id: str) -> None:
        if await self.repo.count_active() >= self.cfg.SANDBOX_MAX_SESSIONS:
            raise CapacityError("the sandbox service is at capacity; try again in a few minutes")
        if await self.repo.count_active(user_id) >= self.cfg.SANDBOX_MAX_SESSIONS_PER_USER:
            raise CapacityError(
                f"you already have {self.cfg.SANDBOX_MAX_SESSIONS_PER_USER} active sandboxes; "
                "finish or reset one in another conversation first"
            )

    async def get(self, session_id: uuid.UUID) -> SandboxSession:
        row = await self.repo.get(session_id)
        if row is None:
            raise SessionNotFound(str(session_id))
        return row

    async def get_or_create(self, conversation_id: str, user_id: str, language: str = "python") -> SandboxSession:
        existing = await self.repo.get_active_for_conversation(conversation_id)
        if existing is not None:
            if existing.user_id != user_id:
                # Conversation ids are platform-issued uuids; a mismatch means a bug or an attack.
                raise SessionNotFound("no sandbox for this conversation")
            return existing

        await self._check_caps(user_id)
        image = image_for(language, self.cfg)
        try:
            row = await self.repo.create(
                conversation_id=conversation_id,
                user_id=user_id,
                language=language,
                image=image,
                status=SessionStatus.CREATING,
            )
            await self.repo.commit()
        except IntegrityError:
            # Lost a race with a concurrent request for the same conversation.
            await self.db.rollback()
            existing = await self.repo.get_active_for_conversation(conversation_id)
            if existing is None or existing.user_id != user_id:
                raise
            return existing

        try:
            row.container_id = await self._acquire_container(image, str(row.id))
            row.status = SessionStatus.READY
        except Exception:
            row.status = SessionStatus.ERROR
            await self.repo.commit()
            raise
        await self.repo.commit()
        return row

    async def ensure_container(self, row: SandboxSession) -> ContainerHandle:
        """Returns a running container for the session, replacing a dead one if needed."""
        if row.status == SessionStatus.TERMINATED:
            raise SessionNotFound("sandbox session was terminated")
        if row.container_id:
            state = await asyncio.to_thread(self.backend.state, row.container_id)
            if state and state.get("Running"):
                return ContainerHandle(row.container_id, workspace_reset=False)
            await asyncio.to_thread(self.backend.remove, row.container_id)
        row.container_id = await self._acquire_container(row.image, str(row.id))
        row.status = SessionStatus.READY
        await self.repo.commit()
        return ContainerHandle(row.container_id, workspace_reset=True)

    async def reset(self, row: SandboxSession) -> SandboxSession:
        if row.status == SessionStatus.TERMINATED:
            raise SessionNotFound("sandbox session was terminated")
        if row.container_id:
            await asyncio.to_thread(self.backend.remove, row.container_id)
            row.container_id = None
        row.container_id = await self._acquire_container(row.image, str(row.id))
        row.status = SessionStatus.READY
        await self.repo.touch(row)
        await self.repo.commit()
        return row

    async def terminate(self, row: SandboxSession, reason: str) -> None:
        if row.container_id:
            await asyncio.to_thread(self.backend.remove, row.container_id)
        await self.repo.mark_terminated(row, reason)
        await self.repo.commit()

    async def touch(self, row: SandboxSession) -> None:
        await self.repo.touch(row)
        await self.repo.commit()
