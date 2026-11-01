"""Data access for SandboxExecution (the audit trail)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import SandboxExecution


class ExecutionRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields) -> SandboxExecution:
        row = SandboxExecution(**fields)
        self.db.add(row)
        await self.db.flush()
        return row
