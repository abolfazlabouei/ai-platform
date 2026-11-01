"""
ExecutionService: one code run end to end —
abuse limits -> per-session Redis lock -> live container -> run -> artifacts -> audit row.

A dead container (OOM, crash, host-side kill) is replaced transparently: the run
that killed it reports what happened, and the next run gets a fresh workspace (the
result says so via `workspace_reset`).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

import redis.asyncio as redis
from redis.exceptions import LockError

from app.core.config import Settings, settings as default_settings
from app.core.redis_client import lock_key
from app.models.sandbox_session import SandboxSession
from app.repositories.execution_repo import ExecutionRepo
from app.sandbox.executor import ContainerLost, ExecutionError, Executor, RunResult
from app.services.artifact_service import ArtifactService
from app.services.session_service import SessionService


class RateLimited(Exception):
    """Per-user rate limit or daily CPU budget exceeded."""


class SessionBusy(Exception):
    """Another execution in the same session did not finish within the lock wait."""


class ExecutionService:
    def __init__(
        self,
        sessions: SessionService,
        executor: Executor,
        artifacts: ArtifactService,
        redis_client: redis.Redis,
        cfg: Settings | None = None,
    ):
        self.sessions = sessions
        self.executor = executor
        self.artifacts = artifacts
        self.redis = redis_client
        self.repo = ExecutionRepo(sessions.db)
        self.cfg = cfg or default_settings

    # --- abuse limits ---

    async def _check_limits(self, user_id: str) -> None:
        now = datetime.now(timezone.utc)
        rate_key = f"sandbox:rate:{user_id}:{now:%Y%m%d%H%M}"
        count = await self.redis.incr(rate_key)
        if count == 1:
            await self.redis.expire(rate_key, 120)
        if count > self.cfg.SANDBOX_RATE_LIMIT_PER_MINUTE:
            raise RateLimited(
                f"rate limit: at most {self.cfg.SANDBOX_RATE_LIMIT_PER_MINUTE} executions per minute; wait a moment"
            )
        used_ms = int(await self.redis.get(self._cpu_key(user_id, now)) or 0)
        if used_ms >= self.cfg.SANDBOX_DAILY_CPU_SECONDS_PER_USER * 1000:
            raise RateLimited("daily sandbox compute budget used up; try again tomorrow")

    @staticmethod
    def _cpu_key(user_id: str, now: datetime) -> str:
        return f"sandbox:cpu:{user_id}:{now:%Y%m%d}"

    async def _charge(self, user_id: str, duration_ms: int) -> None:
        key = self._cpu_key(user_id, datetime.now(timezone.utc))
        await self.redis.incrby(key, duration_ms)
        await self.redis.expire(key, 2 * 24 * 3600)

    # --- run ---

    async def run(self, row: SandboxSession, code: str, timeout_seconds: int | None, language: str = "python") -> dict:
        if language != row.language:
            raise ExecutionError(f"this sandbox runs {row.language}, not {language}")
        await self._check_limits(row.user_id)

        lock = self.redis.lock(
            lock_key(str(row.id)),
            timeout=self.cfg.SANDBOX_MAX_EXEC_SECONDS + self.cfg.SANDBOX_HOST_TIMEOUT_GRACE_SECONDS + 60,
            blocking_timeout=self.cfg.SANDBOX_LOCK_WAIT_SECONDS,
        )
        if not await lock.acquire():
            raise SessionBusy("another execution is still running in this sandbox; try again shortly")
        try:
            return await self._run_locked(row, code, timeout_seconds)
        finally:
            try:
                await lock.release()
            except LockError:
                pass  # expired while running — nothing to release

    async def _run_locked(self, row: SandboxSession, code: str, timeout_seconds: int | None) -> dict:
        handle = await self.sessions.ensure_container(row)
        execution_id = uuid.uuid4()
        t0 = time.monotonic()
        container_lost: ContainerLost | None = None
        try:
            result = await self.executor.run_python(handle.container_id, str(execution_id), code, timeout_seconds)
        except ContainerLost as exc:
            container_lost = exc
            result = RunResult(
                exit_code=None, stdout="", stderr=str(exc), stdout_bytes=0, stderr_bytes=0, truncated=False,
                timed_out=exc.timed_out, oom_killed=exc.oom_killed,
                duration_ms=int((time.monotonic() - t0) * 1000), started_at=time.time(),
            )

        if container_lost is None:
            result.artifacts = await self.artifacts.collect(
                handle.container_id, str(row.id), str(execution_id), result.started_at
            )
        else:
            # Remove the dead/killed box now; the next call gets a fresh one.
            await asyncio.to_thread(self.sessions.backend.remove, handle.container_id)
            row.container_id = None

        await self.repo.create(
            id=execution_id,
            session_id=row.id,
            user_id=row.user_id,
            language=row.language,
            code=code,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            oom_killed=result.oom_killed,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            artifact_keys=[a["key"] for a in result.artifacts if a.get("key")],
        )
        await self.sessions.touch(row)  # commits the audit row too
        await self._charge(row.user_id, result.duration_ms)

        payload = asdict(result)
        payload.pop("started_at", None)
        payload.update(
            execution_id=str(execution_id),
            workspace_reset=handle.workspace_reset,
            sandbox_restarted=container_lost is not None,
        )
        return payload
