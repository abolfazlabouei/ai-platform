"""
Integration fixtures: a real sandbox container built from app.sandbox.spec.

Requires Docker, the sandbox image (SANDBOX_IMAGE_PYTHON) and the runtime
(SANDBOX_RUNTIME, default runsc). For a laptop without gVisor run with
SANDBOX_RUNTIME=runc — every check still runs except the gVisor kernel check.
"""
import asyncio
import uuid

import docker
import pytest

from app.core.config import Settings, settings
from app.sandbox.docker_backend import DockerBackend
from app.sandbox.executor import Executor
from app.sandbox.spec import build_container_kwargs

# Small limits keep the abuse tests fast.
ITEST_CFG = Settings(**{**settings.model_dump(), "SANDBOX_MEMORY": "256m", "SANDBOX_WORKSPACE_SIZE": "32m",
                        "SANDBOX_MAX_EXEC_SECONDS": 20, "SANDBOX_HOST_TIMEOUT_GRACE_SECONDS": 5})


def _docker_ready() -> str | None:
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return f"docker unavailable: {exc}"
    try:
        client.images.get(ITEST_CFG.SANDBOX_IMAGE_PYTHON)
    except docker.errors.ImageNotFound:
        return f"sandbox image {ITEST_CFG.SANDBOX_IMAGE_PYTHON} not built"
    if not DockerBackend(client).runtime_available(ITEST_CFG.SANDBOX_RUNTIME):
        return f"runtime {ITEST_CFG.SANDBOX_RUNTIME} not registered in docker"
    return None


@pytest.fixture(scope="session")
def backend():
    reason = _docker_ready()
    if reason:
        pytest.skip(reason)
    return DockerBackend()


@pytest.fixture
def executor(backend):
    return Executor(backend, ITEST_CFG)


@pytest.fixture
def container(backend):
    kwargs = build_container_kwargs(ITEST_CFG.SANDBOX_IMAGE_PYTHON, session_id=f"itest-{uuid.uuid4()}", cfg=ITEST_CFG)
    cid = backend.create_and_start(kwargs)
    yield cid
    backend.remove(cid)


@pytest.fixture
def run(executor, container):
    async def _run(code: str, timeout: int = 15):
        return await executor.run_python(container, uuid.uuid4().hex, code, timeout)
    return _run
