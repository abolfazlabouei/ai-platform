"""
Process-wide singletons (Docker backend, warm pool, executor) created in the app
lifespan, plus a per-request factory wiring them to a DB session. Used by both the
REST routers and the MCP tools so the two interfaces share one code path.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import get_redis
from app.sandbox.docker_backend import DockerBackend
from app.sandbox.executor import Executor
from app.sandbox.warm_pool import WarmPool
from app.services.artifact_service import ArtifactService
from app.services.execution_service import ExecutionService
from app.services.file_import_service import FileImportService
from app.services.session_service import SessionService


@dataclass
class Runtime:
    backend: DockerBackend
    pool: WarmPool
    executor: Executor


@dataclass
class Services:
    sessions: SessionService
    executions: ExecutionService
    imports: FileImportService
    executor: Executor


_runtime: Runtime | None = None


def init_runtime(backend: DockerBackend | None = None) -> Runtime:
    global _runtime
    backend = backend or DockerBackend()
    _runtime = Runtime(backend=backend, pool=WarmPool(backend, get_redis()), executor=Executor(backend))
    return _runtime


def get_runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("sandbox runtime not initialised (app lifespan did not run)")
    return _runtime


def build_services(db: AsyncSession) -> Services:
    rt = get_runtime()
    sessions = SessionService(db, rt.backend, rt.pool)
    executions = ExecutionService(sessions, rt.executor, ArtifactService(rt.executor), get_redis())
    return Services(
        sessions=sessions,
        executions=executions,
        imports=FileImportService(rt.executor),
        executor=rt.executor,
    )


def sandbox_images() -> list[str]:
    return [settings.SANDBOX_IMAGE_PYTHON]
