"""
The most important unit test in this service: every sandbox container MUST be
created with exactly these security settings (plan section 5.1).
"""
from app.core.config import Settings
from app.sandbox.spec import LABEL_POOL, LABEL_SANDBOX, LABEL_SESSION, build_container_kwargs

CFG = Settings(
    SANDBOX_RUNTIME="runsc",
    SANDBOX_MEMORY="1g",
    SANDBOX_CPUS=1.0,
    SANDBOX_PIDS_LIMIT=128,
    SANDBOX_WORKSPACE_SIZE="512m",
    SANDBOX_TMP_SIZE="64m",
    SANDBOX_NOFILE=1024,
    SANDBOX_MAX_FILE_BYTES=268435456,
)


def _kwargs(session_id="11111111-1111-1111-1111-111111111111"):
    return build_container_kwargs("img:1", session_id=session_id, cfg=CFG)


def test_isolation_settings():
    k = _kwargs()
    assert k["runtime"] == "runsc"
    assert k["network_mode"] == "none"
    assert k["read_only"] is True
    assert k["user"] == "1000:1000"
    assert k["cap_drop"] == ["ALL"]
    assert k["security_opt"] == ["no-new-privileges"]
    assert k["privileged"] is False
    assert k["hostname"] == "sandbox"
    assert k["auto_remove"] is False


def test_writable_paths_are_size_capped_tmpfs_only():
    k = _kwargs()
    assert k["tmpfs"] == {
        "/workspace": "size=512m,uid=1000,gid=1000,mode=0750",
        "/tmp": "size=64m,uid=1000,gid=1000",
    }


def test_no_host_mounts_devices_or_socket():
    k = _kwargs()
    assert k["volumes"] == {}
    assert k["mounts"] == []
    assert k["devices"] == []
    assert "binds" not in k
    assert "docker.sock" not in repr(k)


def test_resource_limits():
    k = _kwargs()
    assert k["mem_limit"] == 1024**3
    assert k["memswap_limit"] == k["mem_limit"]  # no swap escape
    assert k["nano_cpus"] == 1_000_000_000
    assert k["pids_limit"] == 128
    ulimits = {u["Name"]: (u["Soft"], u["Hard"]) for u in k["ulimits"]}
    assert ulimits == {"nofile": (1024, 1024), "fsize": (268435456, 268435456)}


def test_environment_is_allowlisted():
    k = _kwargs()
    assert set(k["environment"]) == {"HOME", "MPLBACKEND", "PYTHONDONTWRITEBYTECODE", "PATH", "MPLCONFIGDIR"}
    assert k["environment"]["HOME"] == "/workspace"
    joined = repr(k["environment"]).lower()
    for secret_hint in ("secret", "key", "token", "password", "database", "redis", "s3_"):
        assert secret_hint not in joined


def test_labels_session_vs_pool():
    session = _kwargs("abc")["labels"]
    assert session == {LABEL_SANDBOX: "1", LABEL_SESSION: "abc"}
    pool = build_container_kwargs("img:1", session_id=None, cfg=CFG)["labels"]
    assert pool == {LABEL_SANDBOX: "1", LABEL_POOL: "1"}


def test_runtime_is_configurable():
    k = build_container_kwargs("img:1", session_id="x", cfg=Settings(SANDBOX_RUNTIME="kata"))
    assert k["runtime"] == "kata"
