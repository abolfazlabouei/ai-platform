"""
The security core: the exact `containers.create` kwargs every sandbox container
gets — session containers and warm-pool containers alike. Nothing derived from a
request (code, paths, user ids beyond the session label) ever reaches these kwargs.

tests/unit/test_spec.py asserts every setting here; change both together.
"""
from __future__ import annotations

from app.core.config import Settings, settings as default_settings

SANDBOX_UID = 1000
SANDBOX_GID = 1000
WORKSPACE = "/workspace"

LABEL_SANDBOX = "ai-platform.sandbox"
LABEL_SESSION = "ai-platform.session_id"
LABEL_POOL = "ai-platform.sandbox.pool"

# The ONLY environment a sandbox ever sees. Never pass the control plane's env.
SANDBOX_ENV = {
    "HOME": WORKSPACE,
    "MPLBACKEND": "Agg",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    # Keeps matplotlib's font cache out of the user-visible /workspace.
    "MPLCONFIGDIR": "/tmp/matplotlib",
}


def _memory_bytes(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    value = value.strip().lower()
    if value[-1] in units:
        return int(float(value[:-1]) * units[value[-1]])
    return int(value)


def build_container_kwargs(image: str, *, session_id: str | None, cfg: Settings | None = None) -> dict:
    """`session_id=None` builds a warm-pool container (labeled as such, no session)."""
    cfg = cfg or default_settings
    memory = _memory_bytes(cfg.SANDBOX_MEMORY)
    labels = {LABEL_SANDBOX: "1"}
    if session_id is None:
        labels[LABEL_POOL] = "1"
    else:
        labels[LABEL_SESSION] = session_id

    return {
        "image": image,
        "command": ["sleep", "infinity"],  # PID 1 is tini via the image ENTRYPOINT
        "detach": True,
        "runtime": cfg.SANDBOX_RUNTIME,
        "network_mode": "none",
        "read_only": True,
        "tmpfs": {
            WORKSPACE: f"size={cfg.SANDBOX_WORKSPACE_SIZE},uid={SANDBOX_UID},gid={SANDBOX_GID},mode=0750",
            "/tmp": f"size={cfg.SANDBOX_TMP_SIZE},uid={SANDBOX_UID},gid={SANDBOX_GID}",
        },
        "user": f"{SANDBOX_UID}:{SANDBOX_GID}",
        "working_dir": WORKSPACE,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "mem_limit": memory,
        "memswap_limit": memory,  # equal to mem_limit => no swap
        "nano_cpus": int(cfg.SANDBOX_CPUS * 1e9),
        "pids_limit": cfg.SANDBOX_PIDS_LIMIT,
        "ulimits": [
            {"Name": "nofile", "Soft": cfg.SANDBOX_NOFILE, "Hard": cfg.SANDBOX_NOFILE},
            {"Name": "fsize", "Soft": cfg.SANDBOX_MAX_FILE_BYTES, "Hard": cfg.SANDBOX_MAX_FILE_BYTES},
        ],
        "environment": dict(SANDBOX_ENV),
        "labels": labels,
        "hostname": "sandbox",
        "auto_remove": False,  # the reaper removes explicitly; keeps a crashed box for post-mortem
        "privileged": False,
        "devices": [],
        "volumes": {},
        "mounts": [],
    }
