"""
Executor: runs code and file operations inside an existing sandbox container.

Code is delivered as a file (/workspace/.runs/<execution_id>.py) through stdin of a
fixed helper, then run with an argv list — never through `sh -c` — so there is no
quoting/injection surface. The in-container `timeout -s KILL` is the first line of
defense; the host-side asyncio deadline (timeout + grace) is the one that is
trusted: if it fires, the whole container is killed and the session must be reset.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.config import Settings, settings as default_settings
from app.sandbox.docker_backend import DockerBackend, ExecOutput
from app.sandbox.files import (
    LIST_HELPER,
    OUTPUTS_DIR,
    READ_HELPER,
    RUNS_DIR,
    SCRIPT_WRITE_HELPER,
    WRITE_HELPER,
    parse_listing,
    resolve_workspace_path,
)
from app.sandbox.spec import SANDBOX_GID, SANDBOX_UID, WORKSPACE

SANDBOX_USER = f"{SANDBOX_UID}:{SANDBOX_GID}"
SUPPORTED_LANGUAGES = {"python"}
_TIMEOUT_EXIT = 124  # GNU timeout's exit status when it fired with a catchable signal
_KILLED_EXIT = 137  # 128 + SIGKILL (also what `timeout -s KILL` returns when it fires)


class ExecutionError(Exception):
    """Expected, user-facing failure (bad input, file problems). Message is safe to show the model."""


class ContainerLost(Exception):
    """The container died or was killed; the session needs a fresh one."""

    def __init__(self, message: str, *, oom_killed: bool = False, timed_out: bool = False):
        super().__init__(message)
        self.oom_killed = oom_killed
        self.timed_out = timed_out


@dataclass
class RunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    truncated: bool
    timed_out: bool
    oom_killed: bool
    duration_ms: int
    started_at: float
    artifacts: list[dict] = field(default_factory=list)


def clamp_timeout(timeout_seconds: int | None, cfg: Settings | None = None) -> int:
    cfg = cfg or default_settings
    if timeout_seconds is None:
        timeout_seconds = cfg.SANDBOX_DEFAULT_EXEC_SECONDS
    return max(1, min(int(timeout_seconds), cfg.SANDBOX_MAX_EXEC_SECONDS))


def validate_code(language: str, code: str, cfg: Settings | None = None) -> None:
    cfg = cfg or default_settings
    if language not in SUPPORTED_LANGUAGES:
        raise ExecutionError(f"unsupported language '{language}'; supported: {sorted(SUPPORTED_LANGUAGES)}")
    if not isinstance(code, str) or not code.strip():
        raise ExecutionError("code is empty")
    if len(code.encode("utf-8")) > cfg.SANDBOX_MAX_CODE_BYTES:
        raise ExecutionError(f"code is larger than {cfg.SANDBOX_MAX_CODE_BYTES} bytes")


class Executor:
    def __init__(self, backend: DockerBackend, cfg: Settings | None = None):
        self.backend = backend
        self.cfg = cfg or default_settings

    async def _exec(self, container_id: str, argv: list[str], *, stdin: bytes | None = None,
                    max_stdout: int | None = None, max_stderr: int | None = None) -> ExecOutput:
        return await asyncio.to_thread(
            self.backend.exec_run,
            container_id,
            argv,
            user=SANDBOX_USER,
            workdir=WORKSPACE,
            stdin=stdin,
            max_stdout=max_stdout or self.cfg.SANDBOX_MAX_OUTPUT_BYTES,
            max_stderr=max_stderr or self.cfg.SANDBOX_MAX_OUTPUT_BYTES,
        )

    # --- files ---

    async def write_file(self, container_id: str, path: str, data: bytes) -> str:
        target = resolve_workspace_path(path)
        out = await self._exec(container_id, ["python3", "-I", "-c", WRITE_HELPER, target], stdin=data)
        if out.exit_code != 0:
            raise ExecutionError(f"could not write {target}: {out.stderr.decode(errors='replace')[:300]}")
        return target

    async def read_file(self, container_id: str, path: str, max_bytes: int) -> tuple[bytes, bool]:
        """Returns (content, truncated)."""
        target = resolve_workspace_path(path)
        out = await self._exec(
            container_id,
            ["python3", "-I", "-c", READ_HELPER, target, str(max_bytes)],
            max_stdout=max_bytes + 1,
        )
        if out.exit_code != 0:
            raise ExecutionError(f"could not read {target}: {out.stderr.decode(errors='replace')[:300]}")
        return out.stdout[:max_bytes], len(out.stdout) > max_bytes

    async def list_files(self, container_id: str, path: str = ".") -> list[dict]:
        target = resolve_workspace_path(path, allow_root=True)
        out = await self._exec(
            container_id, ["python3", "-I", "-c", LIST_HELPER, target], max_stdout=256 * 1024
        )
        if out.exit_code != 0:
            raise ExecutionError(f"could not list {target}: {out.stderr.decode(errors='replace')[:300]}")
        return parse_listing(out.stdout)

    async def new_outputs(self, container_id: str, since_epoch: float) -> list[dict]:
        """Regular files under /workspace/outputs modified at/after `since_epoch`."""
        try:
            entries = await self.list_files(container_id, OUTPUTS_DIR)
        except ExecutionError:
            return []  # outputs/ does not exist
        floor = int(since_epoch) - 1  # mtime has 1s resolution in the listing
        return [e for e in entries if e["type"] == "file" and e["mtime"] >= floor]

    # --- code ---

    async def run_python(self, container_id: str, execution_id: str, code: str, timeout_seconds: int) -> RunResult:
        validate_code("python", code, self.cfg)
        timeout_seconds = clamp_timeout(timeout_seconds, self.cfg)
        script = f"{RUNS_DIR}/{execution_id}.py"
        out = await self._exec(
            container_id, ["python3", "-I", "-c", SCRIPT_WRITE_HELPER, script], stdin=code.encode("utf-8")
        )
        if out.exit_code != 0:
            raise ExecutionError(f"could not stage the script: {out.stderr.decode(errors='replace')[:300]}")
        # outputs/ always exists so the model can save files there without mkdir.
        await self._exec(container_id, ["mkdir", "-p", OUTPUTS_DIR])

        argv = ["timeout", "-s", "KILL", str(timeout_seconds), "python3", "-I", script]
        started = time.time()
        t0 = time.monotonic()
        try:
            out = await asyncio.wait_for(
                self._exec(container_id, argv),
                timeout=timeout_seconds + self.cfg.SANDBOX_HOST_TIMEOUT_GRACE_SECONDS,
            )
        except asyncio.TimeoutError:
            # The in-container timeout is not trusted alone: kill the whole box.
            await asyncio.to_thread(self.backend.kill, container_id)
            raise ContainerLost("execution exceeded the host-side deadline; sandbox was killed", timed_out=True)
        duration_ms = int((time.monotonic() - t0) * 1000)

        state = await asyncio.to_thread(self.backend.state, container_id)
        if state is None or not state.get("Running"):
            oom = bool(state and state.get("OOMKilled"))
            raise ContainerLost(
                "sandbox ran out of memory and was restarted" if oom else "sandbox container stopped unexpectedly",
                oom_killed=oom,
            )

        # With `-s KILL`, GNU timeout exits 128+9 (not 124) when it fires, so elapsed
        # time is what tells our timeout apart from any other SIGKILL.
        reached_limit = duration_ms >= timeout_seconds * 1000 - 100
        timed_out = out.exit_code in (_TIMEOUT_EXIT, _KILLED_EXIT) and reached_limit
        # SIGKILL well before the limit: under runc that is the kernel OOM killer.
        oom_killed = out.exit_code == _KILLED_EXIT and not reached_limit
        return RunResult(
            exit_code=out.exit_code,
            stdout=out.stdout.decode("utf-8", errors="replace"),
            stderr=out.stderr.decode("utf-8", errors="replace"),
            stdout_bytes=out.stdout_total,
            stderr_bytes=out.stderr_total,
            truncated=out.truncated,
            timed_out=timed_out,
            oom_killed=oom_killed,
            duration_ms=duration_ms,
            started_at=started,
        )
