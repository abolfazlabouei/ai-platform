"""agent_service: CRUD business logic for Agent (name, prompt, model, mcp/kb selection, tool policy)."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.repositories.agent_repo import AgentRepo


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AgentRepo(db)

    async def create(
        self,
        user_id: str,
        name: str,
        system_prompt: str,
        description: str | None = None,
        model_config: dict | None = None,
        mcp_server_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        skill_ids: list[dict] | None = None,
        tool_policy: list[dict] | None = None,
        capabilities: list[str] | None = None,
        is_composable: bool = False,
    ) -> Agent:
        return await self.repo.create(
            user_id=user_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            model_config_json=model_config or {},
            mcp_server_ids=mcp_server_ids or [],
            knowledge_base_ids=knowledge_base_ids or [],
            skill_ids=skill_ids or [],
            tool_policy=tool_policy or [],
            capabilities=capabilities or [],
            is_composable=is_composable,
        )

    async def get(self, agent_id: uuid.UUID) -> Agent | None:
        return await self.repo.get(agent_id)

    async def list_for_user(self, user_id: str) -> list[Agent]:
        return await self.repo.list_for_user(user_id)

    async def list_composable(self) -> list[Agent]:
        return await self.repo.list_composable()

    async def update(self, agent: Agent, **fields) -> Agent:
        if "model_config" in fields:
            fields["model_config_json"] = fields.pop("model_config")
        return await self.repo.update(agent, **fields)

    async def delete(self, agent: Agent) -> None:
        await self.repo.delete(agent)
