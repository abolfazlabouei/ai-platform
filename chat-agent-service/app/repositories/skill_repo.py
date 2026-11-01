"""Async queries for skills, versions, files and usage rows. No business rules here."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.skill import Skill, SkillFile, SkillUsage, SkillVersion


class SkillRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, skill_id: uuid.UUID) -> Skill | None:
        return await self.db.get(Skill, skill_id)

    async def get_by_name(self, user_id: str, name: str) -> Skill | None:
        result = await self.db.execute(select(Skill).where(Skill.user_id == user_id, Skill.name == name))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> list[Skill]:
        result = await self.db.execute(select(Skill).where(Skill.user_id == user_id).order_by(Skill.name))
        return list(result.scalars().all())

    async def get_by_ids(self, user_id: str, skill_ids: list[uuid.UUID]) -> list[Skill]:
        if not skill_ids:
            return []
        result = await self.db.execute(select(Skill).where(Skill.user_id == user_id, Skill.id.in_(skill_ids)))
        return list(result.scalars().all())

    async def get_version(self, skill_id: uuid.UUID, version: int) -> SkillVersion | None:
        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id, SkillVersion.version == version)
            .options(selectinload(SkillVersion.files))
        )
        return result.scalar_one_or_none()

    async def get_version_by_id(self, version_id: uuid.UUID) -> SkillVersion | None:
        result = await self.db.execute(
            select(SkillVersion).where(SkillVersion.id == version_id).options(selectinload(SkillVersion.files))
        )
        return result.scalar_one_or_none()

    async def list_versions(self, skill_id: uuid.UUID) -> list[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion).where(SkillVersion.skill_id == skill_id).order_by(SkillVersion.version.desc())
        )
        return list(result.scalars().all())

    async def version_summaries(self, pairs: list[tuple[uuid.UUID, int]]) -> dict[tuple[uuid.UUID, int], SkillVersion]:
        """Light lookup (no files) of (skill_id, version) pairs; bodies are deferred by selecting columns only."""
        if not pairs:
            return {}
        ids = list({skill_id for skill_id, _ in pairs})
        result = await self.db.execute(
            select(
                SkillVersion.id, SkillVersion.skill_id, SkillVersion.version,
                SkillVersion.description, SkillVersion.has_scripts,
            ).where(SkillVersion.skill_id.in_(ids))
        )
        wanted = set(pairs)
        return {
            (row.skill_id, row.version): row for row in result.all() if (row.skill_id, row.version) in wanted
        }

    def add_skill(self, **fields) -> Skill:
        skill = Skill(**fields)
        self.db.add(skill)
        return skill

    def add_version(self, files: list[dict], **fields) -> SkillVersion:
        version = SkillVersion(**fields)
        version.files = [SkillFile(**f) for f in files]
        self.db.add(version)
        return version

    async def delete(self, skill: Skill) -> None:
        await self.db.delete(skill)

    def add_usage(self, **fields) -> SkillUsage:
        row = SkillUsage(**fields)
        self.db.add(row)
        return row

    async def flush(self) -> None:
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()
