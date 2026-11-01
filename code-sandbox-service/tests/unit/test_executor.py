"""Executor logic with the Docker backend faked out."""
import asyncio

import pytest

from app.core.config import Settings
from app.sandbox.docker_backend import ExecOutput
from app.sandbox.executor import ContainerLost, ExecutionError, Executor, clamp_timeout, validate_code

CFG = Settings(SANDBOX_MAX_EXEC_SECONDS=120, SANDBOX_DEFAULT_EXEC_SECONDS=30, SANDBOX_HOST_TIMEOUT_GRACE_SECONDS=0,
               SANDBOX_MAX_OUTPUT_BYTES=10, SANDBOX_MAX_CODE_BYTES=100)


class FakeBackend:
    def __init__(self, run_output: ExecOutput | None = None, state: dict | None = None, hang: float = 0):
        self.calls: list[dict] = []
        self.run_output = run_output or ExecOutput(0, b"ok\n", b"", 3, 0)
        self._state = state if state is not None else {"Running": True}
        self.hang = hang
        self.killed: list[str] = []

    def exec_run(self, container_id, argv, *, user, workdir, stdin=None, max_stdout, max_stderr):
        self.calls.append({"argv": argv, "user": user, "workdir": workdir, "stdin": stdin,
                           "max_stdout": max_stdout})
        if argv[0] == "timeout":
            if self.hang:
                import time
                time.sleep(self.hang)
            return self.run_output
        return ExecOutput(0, b"", b"", 0, 0)

    def state(self, container_id):
        return self._state

    def kill(self, container_id):
        self.killed.append(container_id)


def test_clamp_timeout():
    assert clamp_timeout(None, CFG) == 30
    assert clamp_timeout(0, CFG) == 1
    assert clamp_timeout(-5, CFG) == 1
    assert clamp_timeout(10, CFG) == 10
    assert clamp_timeout(10_000, CFG) == 120


def test_validate_code():
    validate_code("python", "print(1)", CFG)
    with pytest.raises(ExecutionError):
        validate_code("node", "console.log(1)", CFG)
    with pytest.raises(ExecutionError):
        validate_code("python", "   ", CFG)
    with pytest.raises(ExecutionError):
        validate_code("python", "x" * 101, CFG)


async def test_code_is_delivered_as_file_and_run_without_shell():
    backend = FakeBackend()
    result = await Executor(backend, CFG).run_python("cid", "exec-1", "print('hi; rm -rf /')", 5)
    write, mkdir, run = backend.calls[0], backend.calls[1], backend.calls[2]
    assert write["argv"][:3] == ["python3", "-I", "-c"]
    assert write["argv"][-1] == "/tmp/.runs/exec-1.py"
    assert write["stdin"] == b"print('hi; rm -rf /')"
    assert mkdir["argv"] == ["mkdir", "-p", "/workspace/outputs"]
    assert run["argv"] == ["timeout", "-s", "KILL", "5", "python3", "-I", "/tmp/.runs/exec-1.py"]
    assert all(c["user"] == "1000:1000" and c["workdir"] == "/workspace" for c in backend.calls)
    assert not any(c["argv"][0] in ("sh", "bash") for c in backend.calls)
    assert result.exit_code == 0 and result.stdout == "ok\n"


async def test_output_truncation_flag():
    out = ExecOutput(0, b"0123456789", b"", 5000, 0)
    result = await Executor(FakeBackend(run_output=out), CFG).run_python("cid", "e", "print(1)", 5)
    assert result.truncated is True
    assert result.stdout_bytes == 5000
    assert len(result.stdout) == 10


@pytest.mark.parametrize("exit_code", [124, 137])
async def test_in_container_timeout_is_reported(exit_code):
    # `timeout -s KILL` exits 137 when it fires (124 with catchable signals); duration ~= the limit.
    out = ExecOutput(exit_code, b"", b"", 0, 0)
    backend = FakeBackend(run_output=out, hang=1.0)
    result = await Executor(backend, Settings(**{**CFG.model_dump(), "SANDBOX_HOST_TIMEOUT_GRACE_SECONDS": 5})) \
        .run_python("cid", "e", "while True: pass", 1)
    assert result.timed_out is True
    assert result.oom_killed is False


async def test_sigkill_without_timeout_is_oom():
    out = ExecOutput(137, b"", b"", 0, 0)
    result = await Executor(FakeBackend(run_output=out), CFG).run_python("cid", "e", "x", 30)
    assert result.oom_killed is True
    assert result.timed_out is False


async def test_host_deadline_kills_container():
    backend = FakeBackend(hang=1.5)
    with pytest.raises(ContainerLost) as info:
        await Executor(backend, CFG).run_python("cid", "e", "while True: pass", 1)
    assert info.value.timed_out is True
    assert backend.killed == ["cid"]
    await asyncio.sleep(0.6)  # let the worker thread finish before the loop closes


async def test_dead_container_after_run_reports_oom():
    backend = FakeBackend(state={"Running": False, "OOMKilled": True})
    with pytest.raises(ContainerLost) as info:
        await Executor(backend, CFG).run_python("cid", "e", "x", 5)
    assert info.value.oom_killed is True


async def test_write_rejects_escaping_path_before_any_exec():
    backend = FakeBackend()
    with pytest.raises(ValueError):
        await Executor(backend, CFG).write_file("cid", "../../etc/x", b"data")
    assert backend.calls == []
