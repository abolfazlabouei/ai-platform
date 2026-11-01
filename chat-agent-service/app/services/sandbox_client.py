"""
REST client for code-sandbox-service, used by skill_run_script. The sandbox trusts the shared
key (X-Sandbox-Key) — this service is the only caller — and takes user_id/conversation_id in
the request body. (Its MCP interface instead derives identity from a signed JWT; see
mcp_manager/client_pool.py.)
"""
from __future__ import annotations

import base64

import httpx

from app.core.config import settings


class SandboxError(Exception):
    """A sandbox failure whose message is safe to show the model."""


class SandboxClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.SANDBOX_BASE_URL.rstrip("/"),
            headers={"X-Sandbox-Key": settings.SANDBOX_SHARED_SECRET},
            timeout=settings.SANDBOX_REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    async def _call(self, method: str, url: str, **kwargs) -> dict:
        try:
            async with self._client() as client:
                response = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise SandboxError(f"the code sandbox is unreachable ({type(exc).__name__})") from None
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            if response.status_code == 401:
                detail = "this service is not authorized for the sandbox (check SANDBOX_SHARED_SECRET)"
            raise SandboxError(str(detail)[:500])
        return response.json()

    async def get_or_create_session(self, conversation_id: str, user_id: str) -> str:
        data = await self._call(
            "POST", "/api/v1/sessions",
            json={"conversation_id": conversation_id, "user_id": user_id, "language": "python"},
        )
        return data["id"]

    async def import_skill(self, session_id: str, name: str, files: list[tuple[str, bytes]]) -> dict:
        return await self._call(
            "POST", f"/api/v1/sessions/{session_id}/imports/skill",
            json={"name": name, "files": [
                {"path": path, "content_base64": base64.b64encode(data).decode()} for path, data in files
            ]},
        )

    async def import_document(self, session_id: str, file_id: str) -> dict:
        return await self._call("POST", f"/api/v1/sessions/{session_id}/imports", json={"file_id": file_id})

    async def execute(self, session_id: str, code: str, timeout_seconds: int) -> dict:
        return await self._call(
            "POST", f"/api/v1/sessions/{session_id}/executions",
            json={"code": code, "timeout_seconds": timeout_seconds},
        )
