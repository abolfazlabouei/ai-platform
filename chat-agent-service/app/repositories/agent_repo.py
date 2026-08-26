"""Async CRUD queries for Agent."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent


class AgentRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Agent:
        agent = Agent(**kwargs)
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get(self, agent_id: uuid.UUID) -> Agent | None:
        return await self.db.get(Agent, agent_id)

    async def list_for_user(self, user_id: str) -> list[Agent]:
        result = await self.db.execute(select(Agent).where(Agent.user_id == user_id))
        return list(result.scalars().all())

    async def list_composable(self) -> list[Agent]:
        """Used by the (future) multi-agent-orchestrator-service's agent registry."""
        result = await self.db.execute(select(Agent).where(Agent.is_composable.is_(True)))
        return list(result.scalars().all())

    async def update(self, agent: Agent, **kwargs) -> Agent:
        for key, value in kwargs.items():
            setattr(agent, key, value)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete(self, agent: Agent) -> None:
        await self.db.delete(agent)
        await self.db.commit()
