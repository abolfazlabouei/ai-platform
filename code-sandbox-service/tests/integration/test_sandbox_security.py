"""
Security and behavior checks against a real sandbox container (plan section 12).
Run on the target server with the real runtime:
    pytest -m integration tests/integration
"""
import json
import time

import pytest

from app.sandbox.executor import ContainerLost, ExecutionError
from app.sandbox.files import PathError
from tests.integration.conftest import ITEST_CFG

pytestmark = pytest.mark.integration


async def test_hello(run):
    r = await run("print(1+1)")
    assert r.exit_code == 0
    assert r.stdout == "2\n"


async def test_preinstalled_stack_imports(run):
    r = await run("import numpy, pandas, matplotlib, scipy, sklearn, openpyxl, docx, fitz, tabulate; print('ok')", 60)
    assert r.exit_code == 0, r.stderr
    assert r.stdout.strip() == "ok"


async def test_matplotlib_is_quiet_on_stderr(run):
    r = await run("import matplotlib.pyplot as plt; plt.plot([1, 2]); print('ok')", 60)
    assert r.exit_code == 0 and r.stderr == "", r.stderr


async def test_chart_lands_in_outputs(run, executor, container):
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.bar(['فروردین','اردیبهشت'], [3, 5]); plt.title('فروش ماهانه')\n"
        "plt.savefig('/workspace/outputs/chart.png')\n"
    )
    r = await run(code, 60)
    assert r.exit_code == 0, r.stderr
    outputs = await executor.new_outputs(container, r.started_at)
    assert [o["path"] for o in outputs] == ["outputs/chart.png"]
    data, truncated = await executor.read_file(container, "outputs/chart.png", 5_000_000)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and not truncated


@pytest.mark.parametrize("target", [("1.1.1.1", 53), ("postgres", 5432), ("redis", 6379), ("minio", 9000),
                                    ("169.254.169.254", 80), ("host.docker.internal", 80), ("172.17.0.1", 2375)])
async def test_no_network(run, target):
    host, port = target
    code = (
        "import socket\n"
        f"try:\n    socket.create_connection(({host!r}, {port}), timeout=3); print('CONNECTED')\n"
        "except Exception as e:\n    print('blocked', type(e).__name__)\n"
    )
    r = await run(code)
    assert "CONNECTED" not in r.stdout
    assert r.stdout.startswith("blocked")


async def test_only_allowlisted_env(run):
    r = await run("import os, json; print(json.dumps(sorted(os.environ)))")
    keys = set(json.loads(r.stdout))
    assert keys <= {"HOME", "MPLBACKEND", "PYTHONDONTWRITEBYTECODE", "PATH", "MPLCONFIGDIR", "HOSTNAME", "LANG",
                    "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "MATPLOTLIBRC"}, keys  # last ones: public image ENV
    assert not any(k.startswith(("S3_", "SANDBOX_", "DATABASE", "REDIS", "JWT")) for k in keys)


async def test_runs_as_unprivileged_user_on_readonly_root(run):
    r = await run(
        "import os\n"
        "print(os.getuid(), os.getgid())\n"
        "for p in ['/etc/x', '/usr/x', '/x']:\n"
        "    try:\n        open(p, 'w'); print('WROTE', p)\n"
        "    except OSError as e:\n        print('denied', p)\n"
    )
    assert r.stdout.splitlines()[0] == "1000 1000"
    assert "WROTE" not in r.stdout


async def test_memory_limit_kills(run, backend, container):
    try:
        r = await run("b = bytearray(512 * 1024 * 1024); print('allocated', len(b))")
    except ContainerLost as lost:  # gVisor: the whole sandbox is OOM-killed
        assert lost.oom_killed or "stopped" in str(lost)
        return
    assert "allocated" not in r.stdout
    assert r.oom_killed or r.exit_code != 0


async def test_fork_bomb_is_contained(run, backend, container):
    code = (
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    for _ in range(10000):\n"
        "        if os.fork() == 0:\n            time.sleep(30); os._exit(0)\n"
        "        n += 1\n"
        "except OSError as e:\n    print('stopped at', n, type(e).__name__)\n"
    )
    r = await run(code, 10)
    assert "stopped at" in r.stdout
    assert int(r.stdout.split()[2]) < ITEST_CFG.SANDBOX_PIDS_LIMIT
    assert backend.ping()


async def test_infinite_loop_times_out(run):
    t0 = time.monotonic()
    r = await run("while True: pass", 2)
    assert r.timed_out is True
    assert time.monotonic() - t0 < 2 + ITEST_CFG.SANDBOX_HOST_TIMEOUT_GRACE_SECONDS


async def test_filling_workspace_is_a_clean_error(run):
    r = await run(
        "try:\n"
        "    with open('/workspace/big', 'wb') as f:\n"
        "        for _ in range(100): f.write(b'x' * 1024 * 1024)\n"
        "except OSError as e:\n    print('full', e.errno)\n"
    )
    assert "full" in r.stdout
    r2 = await run("import os; os.remove('/workspace/big'); print('still usable')")
    assert r2.stdout.strip() == "still usable"


async def test_output_is_capped(run):
    r = await run("print('x' * 1_000_000)")
    assert r.truncated is True
    assert len(r.stdout.encode()) <= ITEST_CFG.SANDBOX_MAX_OUTPUT_BYTES
    assert r.stdout_bytes > 1_000_000


async def test_write_read_roundtrip_and_listing(executor, container):
    await executor.write_file(container, "notes/a.txt", "سلام".encode())
    data, _ = await executor.read_file(container, "notes/a.txt", 1000)
    assert data.decode() == "سلام"
    paths = [e["path"] for e in await executor.list_files(container, ".")]
    assert "notes/a.txt" in paths


async def test_path_escape_via_argument_rejected(executor, container):
    with pytest.raises(PathError):
        await executor.write_file(container, "../../etc/x", b"x")


async def test_path_escape_via_symlink_rejected(run, executor, container):
    await run("import os; os.symlink('/etc', '/workspace/etc_link'); os.symlink('/etc/passwd', '/workspace/pw')")
    with pytest.raises(ExecutionError):
        await executor.read_file(container, "pw", 1000)
    with pytest.raises(ExecutionError):
        await executor.write_file(container, "etc_link/evil", b"x")


async def test_gvisor_kernel(run):
    if ITEST_CFG.SANDBOX_RUNTIME not in ("runsc", "runsc-kvm"):
        pytest.skip("not running under gVisor")
    r = await run("import platform; print(platform.release())")
    dmesg = await run("import subprocess; print(subprocess.run(['dmesg'], capture_output=True, text=True).stdout)")
    assert "gVisor" in dmesg.stdout or r.stdout.strip() == "4.4.0", (r.stdout, dmesg.stdout)
