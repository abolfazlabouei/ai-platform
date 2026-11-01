"""
Workspace file operations shared by the REST API and the MCP tools: text-only
write/read with size caps, listing, and document import. Every operation resolves
a live container first (replacing a dead one) and refreshes last_used_at.
"""
from __future__ import annotations

import base64
import binascii

from app.core.config import settings
from app.models.sandbox_session import SandboxSession
from app.sandbox.executor import ExecutionError
from app.sandbox.files import SKILLS_DIR, resolve_skill_path, resolve_workspace_path
from app.services.runtime import Services


async def write_text(svc: Services, row: SandboxSession, path: str, content: str) -> str:
    data = content.encode("utf-8")
    if len(data) > settings.SANDBOX_MAX_WRITE_BYTES:
        raise ExecutionError(f"content is larger than {settings.SANDBOX_MAX_WRITE_BYTES} bytes")
    handle = await svc.sessions.ensure_container(row)
    target = await svc.executor.write_file(handle.container_id, path, data)
    await svc.sessions.touch(row)
    return target


async def read_text(svc: Services, row: SandboxSession, path: str) -> tuple[str, str, bool]:
    """Returns (resolved_path, text, truncated)."""
    handle = await svc.sessions.ensure_container(row)
    data, truncated = await svc.executor.read_file(handle.container_id, path, settings.SANDBOX_MAX_READ_BYTES)
    await svc.sessions.touch(row)
    try:
        # A multi-byte char may be cut at the truncation point; drop only that tail.
        text = data.decode("utf-8") if not truncated else data.decode("utf-8", errors="ignore")
    except UnicodeDecodeError:
        raise ExecutionError(
            "this is a binary file; inspect it with run_python, or save results to /workspace/outputs/ "
            "to return them as an artifact"
        ) from None
    if "\x00" in text:
        raise ExecutionError("this is a binary file; inspect it with run_python instead")
    return resolve_workspace_path(path), text, truncated


async def list_dir(svc: Services, row: SandboxSession, path: str = ".") -> list[dict]:
    handle = await svc.sessions.ensure_container(row)
    entries = await svc.executor.list_files(handle.container_id, path)
    await svc.sessions.touch(row)
    return entries


async def import_document(svc: Services, row: SandboxSession, file_id: str) -> dict:
    handle = await svc.sessions.ensure_container(row)
    result = await svc.imports.import_file(handle.container_id, file_id)
    await svc.sessions.touch(row)
    return result


SKILL_IMPORT_MAX_BYTES = 25 * 1024 * 1024


async def import_skill(svc: Services, row: SandboxSession, name: str, files: list[tuple[str, str]]) -> dict:
    """Copies a skill's files (path, base64) into /workspace/skills/<name>/. Everything is validated before the
    first byte is written, so a bad path never leaves a half-imported skill."""
    decoded: list[tuple[str, bytes]] = []
    total = 0
    for rel, b64 in files:
        target = resolve_skill_path(name, rel)
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise ExecutionError(f"{rel}: content is not valid base64") from None
        total += len(data)
        if total > SKILL_IMPORT_MAX_BYTES:
            raise ExecutionError(f"skill files are larger than {SKILL_IMPORT_MAX_BYTES // (1024 * 1024)} MB")
        decoded.append((target, data))
    handle = await svc.sessions.ensure_container(row)
    for target, data in decoded:
        await svc.executor.write_file(handle.container_id, target, data)
    await svc.sessions.touch(row)
    return {"path": f"{SKILLS_DIR}/{name}", "files": len(decoded), "size": total}
