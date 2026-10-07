"""Typed HTTP client wrapper for knowledge-service."""
from __future__ import annotations

import httpx

from app.core.config import settings


class KnowledgeClient:
    def __init__(self):
        self.base_url = settings.KNOWLEDGE_SERVICE_URL

    async def search(self, kb_ids: list[str], query: str, top_k: int = 6) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            resp = await client.post("/api/v1/search", json={"kb_ids": kb_ids, "query": query, "top_k": top_k})
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def list_knowledge_bases(self, bearer_token: str | None = None) -> list[dict]:
        """
        knowledge-service's GET /knowledge-bases is user-scoped via JWT (require_user),
        not a user_id query param — so this forwards the same bearer token the
        chat-agent-service request itself was authenticated with, rather than trying
        to pass user_id directly (which knowledge-service has no way to trust anyway).
        """
        headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get("/api/v1/knowledge-bases", headers=headers)
            resp.raise_for_status()
            return resp.json()
