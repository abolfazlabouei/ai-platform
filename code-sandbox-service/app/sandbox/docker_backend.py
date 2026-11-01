"""
DockerBackend: ALL Docker SDK calls live here — one place to audit what the
control plane does with the Docker socket (which is root-equivalent on the host).

Every method is synchronous (the Docker SDK is blocking); async callers wrap them
with asyncio.to_thread.

File transfer note: sandbox writable paths are tmpfs mounts. Under gVisor those
live inside the sandbox kernel's memory, so the host-side archive API
(put_archive / get_archive) cannot see them. Every byte in or out therefore goes
through `docker exec` stdin/stdout — see exec_run.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import docker
from docker.errors import APIError, NotFound
from docker.utils.socket import STDERR, STDOUT, frames_iter

from app.core.config import settings
from app.sandbox.spec import LABEL_SANDBOX, SANDBOX_ENV


@dataclass
class ExecOutput:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    stdout_total: int
    stderr_total: int

    @property
    def truncated(self) -> bool:
        return self.stdout_total > len(self.stdout) or self.stderr_total > len(self.stderr)


@dataclass
class ContainerInfo:
    id: str
    labels: dict
    running: bool


class DockerBackend:
    def __init__(self, client: docker.DockerClient | None = None):
        # Socket timeout must outlive the longest exec, or a quiet long-running
        # program would make the stream read time out on the host side.
        self._client = client or docker.from_env(
            timeout=settings.SANDBOX_MAX_EXEC_SECONDS + settings.SANDBOX_HOST_TIMEOUT_GRACE_SECONDS + 30
        )

    # --- daemon ---

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:  # noqa: BLE001 — health probe
            return False

    def runtime_available(self, runtime: str) -> bool:
        if runtime == "runc":
            return True
        try:
            return runtime in (self._client.info().get("Runtimes") or {})
        except Exception:  # noqa: BLE001 — health probe
            return False

    # --- containers ---

    def create_and_start(self, kwargs: dict) -> str:
        container = self._client.containers.run(**kwargs)
        return container.id

    def remove(self, container_id: str) -> None:
        try:
            self._client.api.remove_container(container_id, force=True)
        except NotFound:
            pass

    def kill(self, container_id: str) -> None:
        try:
            self._client.api.kill(container_id)
        except (NotFound, APIError):
            pass  # already dead / not running

    def state(self, container_id: str) -> dict | None:
        """Container State dict (Running, OOMKilled, ExitCode, ...) or None if gone."""
        try:
            return self._client.api.inspect_container(container_id)["State"]
        except NotFound:
            return None

    def list_sandbox_containers(self) -> list[ContainerInfo]:
        raw = self._client.api.containers(all=True, filters={"label": f"{LABEL_SANDBOX}=1"})
        return [
            ContainerInfo(id=c["Id"], labels=c.get("Labels") or {}, running=c.get("State") == "running")
            for c in raw
        ]

    # --- exec ---

    def exec_run(
        self,
        container_id: str,
        argv: list[str],
        *,
        user: str,
        workdir: str,
        stdin: bytes | None = None,
        max_stdout: int,
        max_stderr: int,
    ) -> ExecOutput:
        """
        Runs argv (never a shell string) inside the container. Optional stdin bytes
        are streamed in and then half-closed. stdout/stderr are read incrementally:
        at most max_* bytes are kept, the rest is drained and only counted.
        """
        api = self._client.api
        exec_id = api.exec_create(
            container_id,
            argv,
            stdin=stdin is not None,
            stdout=True,
            stderr=True,
            tty=False,
            user=user,
            workdir=workdir,
            environment=dict(SANDBOX_ENV),
        )["Id"]
        sock = api.exec_start(exec_id, socket=True)
        raw = getattr(sock, "_sock", sock)
        out, err = bytearray(), bytearray()
        out_total = err_total = 0
        try:
            if stdin is not None:
                raw.sendall(stdin)
                raw.shutdown(socket.SHUT_WR)
            for stream_id, data in frames_iter(sock, False):
                if stream_id == STDOUT:
                    out_total += len(data)
                    if len(out) < max_stdout:
                        out.extend(data[: max_stdout - len(out)])
                elif stream_id == STDERR:
                    err_total += len(data)
                    if len(err) < max_stderr:
                        err.extend(data[: max_stderr - len(err)])
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass

        exit_code = None
        for _ in range(20):  # the stream can close a moment before the exec is reaped
            info = api.exec_inspect(exec_id)
            if not info.get("Running"):
                exit_code = info.get("ExitCode")
                break
            time.sleep(0.05)
        return ExecOutput(exit_code, bytes(out), bytes(err), out_total, err_total)
