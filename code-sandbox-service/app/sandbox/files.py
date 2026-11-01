"""
Workspace path rules + the tiny in-container helpers used for file transfer.

Path rule (defense in depth — the container itself is the security boundary):
every user-supplied path is normalized on the host and must stay under /workspace;
the in-container helpers then re-check the *resolved* path (realpath, i.e. after
following symlinks the sandboxed code may have created) before touching anything.

Helpers run as `python3 -I -c <HELPER> <args...>` with an argv list — no shell, no
string interpolation of user input into code. They are fixed strings below.
"""
from __future__ import annotations

import posixpath
import re

from app.sandbox.spec import WORKSPACE

INPUTS_DIR = f"{WORKSPACE}/inputs"
OUTPUTS_DIR = f"{WORKSPACE}/outputs"
# Run scripts live on the separate /tmp tmpfs so a full /workspace cannot brick the session.
RUNS_DIR = "/tmp/.runs"


class PathError(ValueError):
    """User-supplied path is not an allowed workspace path."""


def resolve_workspace_path(path: str, *, allow_root: bool = False) -> str:
    """Normalizes `path` (relative to /workspace, or absolute under it) or raises PathError."""
    if not isinstance(path, str) or path.strip() == "":
        raise PathError("path must be a non-empty string")
    if "\x00" in path:
        raise PathError("path contains a NUL byte")
    if "\\" in path:
        raise PathError("backslashes are not allowed in paths")
    if any(part == ".." for part in path.split("/")):
        raise PathError("'..' is not allowed in paths")
    candidate = path if path.startswith("/") else posixpath.join(WORKSPACE, path)
    normalized = posixpath.normpath(candidate)
    if normalized == WORKSPACE:
        if allow_root:
            return normalized
        raise PathError("path must name a file inside /workspace")
    if not normalized.startswith(WORKSPACE + "/"):
        raise PathError("path must be inside /workspace")
    return normalized


SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SKILLS_DIR = f"{WORKSPACE}/skills"


def resolve_skill_path(skill_name: str, rel_path: str) -> str:
    """/workspace/skills/<name>/<rel_path> for a skill file shipped by chat-agent-service. The name must be
    a slug and the relative path must stay inside the skill folder (same rules as every other write)."""
    if not SKILL_NAME_RE.match(skill_name or ""):
        raise PathError("skill name must be a slug")
    if rel_path.startswith("/"):
        raise PathError("skill file paths must be relative")
    full = resolve_workspace_path(f"skills/{skill_name}/{rel_path}")
    if not full.startswith(f"{SKILLS_DIR}/{skill_name}/"):
        raise PathError("skill file path escapes its folder")
    return full


def sanitize_filename(name: str) -> str:
    """Basename-only, safe file name for imported documents."""
    base = posixpath.basename((name or "").replace("\\", "/")).replace("\x00", "")
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    if base in ("", ".", ".."):
        base = "document"
    return base[:200]


# --- in-container helpers ---------------------------------------------------


def _guard(root: str) -> str:
    return (
        "import os,sys\n"
        f"W={root!r}\n"
        "def guard(p):\n"
        "    r=os.path.realpath(p)\n"
        "    if r!=W and not r.startswith(W+'/'):\n"
        "        sys.stderr.write('path escapes '+W);sys.exit(3)\n"
        "    return r\n"
    )


def _write_helper(root: str) -> str:
    # argv: <path>  — stdin is the file content. Writes atomically via a temp file +
    # rename, so an existing symlink at <path> is replaced, never followed.
    return _guard(root) + (
        "p=sys.argv[1]\n"
        "d=guard(os.path.dirname(p) or W)\n"
        "os.makedirs(d,exist_ok=True)\n"
        "guard(d)\n"
        "t=os.path.join(d,'.tmp-'+str(os.getpid()))\n"
        "with open(t,'wb') as f:\n"
        "    while True:\n"
        "        b=sys.stdin.buffer.read(1<<20)\n"
        "        if not b: break\n"
        "        f.write(b)\n"
        "os.replace(t,os.path.join(d,os.path.basename(p)))\n"
    )


WRITE_HELPER = _write_helper(WORKSPACE)
# Same helper, confined to the run-script directory (used only for the code we execute).
SCRIPT_WRITE_HELPER = _write_helper(RUNS_DIR)

_WORKSPACE_GUARD = _guard(WORKSPACE)

# argv: <path> <max_bytes>  — stdout is the content (at most max_bytes+1 bytes, so
# the host can tell truncation apart). Exit 4 if not a regular file.
READ_HELPER = _WORKSPACE_GUARD + (
    "p=guard(sys.argv[1]);n=int(sys.argv[2])\n"
    "if not os.path.isfile(p):\n"
    "    sys.stderr.write('not a regular file');sys.exit(4)\n"
    "with open(p,'rb') as f:\n"
    "    sys.stdout.buffer.write(f.read(n+1))\n"
)

# argv: <dir>  — stdout is one line per entry: "<type>\t<size>\t<mtime>\t<relpath>",
# recursive, symlinks reported but not followed.
LIST_HELPER = _WORKSPACE_GUARD + (
    "root=guard(sys.argv[1])\n"
    "if not os.path.isdir(root):\n"
    "    sys.stderr.write('not a directory');sys.exit(4)\n"
    "for dp,dns,fns in os.walk(root):\n"
    "    for n in sorted(dns)+sorted(fns):\n"
    "        fp=os.path.join(dp,n);st=os.lstat(fp)\n"
    "        k='l' if os.path.islink(fp) else ('d' if os.path.isdir(fp) else 'f')\n"
    "        print(k,st.st_size,int(st.st_mtime),os.path.relpath(fp,W),sep='\\t')\n"
)


def parse_listing(stdout: bytes) -> list[dict]:
    entries = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        kind, size, mtime, rel = parts
        entries.append(
            {
                "path": rel,
                "type": {"f": "file", "d": "dir", "l": "symlink"}.get(kind, "other"),
                "size": int(size),
                "mtime": int(mtime),
            }
        )
    return entries
