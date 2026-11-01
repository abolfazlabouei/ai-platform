"""
skill_service: lifecycle of skills — create / new version / edit / enable / delete /
download — plus the two lookups the chat runtime needs (resolve an agent's skill refs
to enabled versions, and load a version's files).

Versions are immutable: any change creates N+1 (an identical package returns the
existing version instead). Files live in object storage; the SKILL.md body lives in
Postgres because it is read on every skill_load.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.skill import Skill, SkillVersion
from app.repositories.agent_repo import AgentRepo
from app.repositories.skill_repo import SkillRepo
from app.skills import package as pkg
from app.skills.errors import SkillConflict, SkillNotFound, SkillValidationError
from app.skills.storage import SkillStorage, file_key, get_storage, skill_id_prefix


@dataclass
class SaveResult:
    skill: Skill
    version: SkillVersion
    created_version: bool  # False when an identical package already existed
    warnings: list[str]


def parse_skill_ref(ref: dict) -> tuple[uuid.UUID, int | None]:
    return uuid.UUID(str(ref["skill_id"])), (int(ref["version"]) if ref.get("version") is not None else None)


class SkillService:
    def __init__(self, db: AsyncSession, storage: SkillStorage | None = None):
        self.db = db
        self.repo = SkillRepo(db)
        self.storage = storage or get_storage()

    # ---------- reads ----------

    async def get_owned(self, user_id: str, skill_id: uuid.UUID) -> Skill:
        skill = await self.repo.get(skill_id)
        if skill is None or skill.user_id != user_id:
            raise SkillNotFound("skill not found")
        return skill

    async def get_version(self, skill: Skill, version: int | None = None) -> SkillVersion:
        row = await self.repo.get_version(skill.id, version or skill.latest_version)
        if row is None:
            raise SkillNotFound(f"version {version} not found")
        return row

    async def list_with_usage(self, user_id: str) -> list[dict]:
        skills = await self.repo.list_for_user(user_id)
        agents = await AgentRepo(self.db).list_for_user(user_id)
        used_by: dict[str, int] = {}
        for agent in agents:
            for ref in agent.skill_ids or []:
                used_by[str(ref.get("skill_id"))] = used_by.get(str(ref.get("skill_id")), 0) + 1
        latest = await self.repo.version_summaries([(s.id, s.latest_version) for s in skills])
        return [
            {"skill": s, "has_scripts": bool(latest.get((s.id, s.latest_version)) and latest[(s.id, s.latest_version)].has_scripts),
             "used_by_agents": used_by.get(str(s.id), 0)}
            for s in skills
        ]

    # ---------- writes ----------

    async def _store(self, user_id: str, skill: Skill, version: int, package: pkg.SkillPackage) -> list[dict]:
        rows = []
        for f in package.files:
            key = file_key(user_id, skill.id, version, f.path)
            await self.storage.put(key, f.data, f.mime)
            rows.append({"path": f.path, "size_bytes": len(f.data), "mime": f.mime, "storage_key": key, "sha256": f.sha256})
        return rows

    async def save_package(
        self, user_id: str, package: pkg.SkillPackage, *, update: bool, expected_name: str | None = None
    ) -> SaveResult:
        """Create v1, or (when `update` / `expected_name`) add the next version of the same-named skill."""
        if expected_name is not None and package.name != expected_name:
            raise SkillValidationError(f"'name' must stay '{expected_name}' when updating (got '{package.name}')")
        existing = await self.repo.get_by_name(user_id, package.name)
        if existing is not None and not (update or expected_name is not None):
            raise SkillConflict(f"a skill named '{package.name}' already exists; upload with update=true to add a new version")
        if expected_name is not None and existing is None:
            raise SkillNotFound("skill not found")

        if existing is not None:
            latest = await self.repo.get_version(existing.id, existing.latest_version)
            if latest is not None and latest.checksum == package.checksum:
                return SaveResult(existing, latest, False, package.warnings)
            skill, number = existing, existing.latest_version + 1
        else:
            skill = self.repo.add_skill(
                user_id=user_id, name=package.name, description=package.description, latest_version=1, is_enabled=True
            )
            await self.repo.flush()
            number = 1

        try:
            files = await self._store(user_id, skill, number, package)
            version = self.repo.add_version(
                files,
                skill_id=skill.id, version=number, description=package.description, body=package.body,
                frontmatter=package.frontmatter, has_scripts=package.has_scripts,
                total_bytes=package.total_bytes, checksum=package.checksum, created_by=user_id,
            )
            skill.description, skill.latest_version = package.description, number
            await self.repo.commit()
        except Exception:
            await self.repo.rollback()
            await self.storage.delete_prefix(f"{skill_id_prefix(user_id, skill.id)}v{number}/")
            raise
        await self.db.refresh(skill)
        return SaveResult(skill, version, True, package.warnings)

    async def edit(
        self, user_id: str, skill: Skill, skill_md: str, files: dict[str, str] | None, remove: list[str] | None
    ) -> SaveResult:
        """New version from the latest one: SKILL.md replaced, text `files` added/replaced, `remove` dropped, rest carried over."""
        latest = await self.get_version(skill)
        removed = {pkg.normalize_path(p) for p in (remove or [])}
        if pkg.SKILL_MD in removed:
            raise SkillValidationError("SKILL.md cannot be removed")
        overlay = {pkg.normalize_path(p): c for p, c in (files or {}).items()}
        if pkg.SKILL_MD in overlay:
            raise SkillValidationError("SKILL.md goes in 'skill_md', not in 'files'")

        raw: dict[str, bytes] = {pkg.SKILL_MD: skill_md.encode("utf-8")}
        for f in latest.files:
            if f.path == pkg.SKILL_MD or f.path in removed or f.path in overlay:
                continue
            raw[f.path] = await self.storage.get(f.storage_key)
        for path, content in overlay.items():
            raw[path] = content.encode("utf-8")
        package = pkg.assemble(raw, settings)
        return await self.save_package(user_id, package, update=True, expected_name=skill.name)

    async def set_enabled(self, skill: Skill, enabled: bool) -> Skill:
        skill.is_enabled = enabled
        await self.repo.commit()
        await self.db.refresh(skill)
        return skill

    async def delete(self, user_id: str, skill: Skill) -> None:
        skill_id = skill.id
        await self.repo.delete(skill)
        await self.repo.commit()
        await self.storage.delete_prefix(skill_id_prefix(user_id, skill_id))

    # ---------- files ----------

    async def read_file(self, version: SkillVersion, path: str) -> tuple[bytes, str]:
        """(bytes, mime) of an exact stored path; unknown paths raise SkillNotFound (no traversal possible)."""
        entry = next((f for f in version.files if f.path == path), None)
        if entry is None:
            raise SkillNotFound(f"file '{path}' not found in this skill")
        try:
            return await self.storage.get(entry.storage_key), entry.mime
        except KeyError:
            raise SkillNotFound(f"file '{path}' is missing from storage") from None

    async def build_download(self, version: SkillVersion) -> bytes:
        items = []
        for f in version.files:
            data, _ = await self.read_file(version, f.path)
            items.append((f.path, data))
        return pkg.build_zip(items)

    # ---------- agents / runtime ----------

    async def validate_refs(self, user_id: str, refs: list[dict]) -> list[dict]:
        """For agent/chat create+update: every referenced skill must be the user's, a pinned version must exist."""
        normalized, seen = [], set()
        parsed = [parse_skill_ref(r) for r in refs]
        skills = {s.id: s for s in await self.repo.get_by_ids(user_id, [sid for sid, _ in parsed])}
        for skill_id, version in parsed:
            if skill_id in seen:
                raise SkillValidationError("the same skill is attached twice")
            seen.add(skill_id)
            skill = skills.get(skill_id)
            if skill is None:
                raise SkillNotFound(f"skill {skill_id} not found")
            if version is not None and not (1 <= version <= skill.latest_version):
                raise SkillValidationError(f"skill '{skill.name}' has no version {version}")
            normalized.append({"skill_id": str(skill_id), "version": version})
        if len(normalized) > settings.SKILLS_MAX_PER_AGENT:
            raise SkillValidationError(f"at most {settings.SKILLS_MAX_PER_AGENT} skills can be attached")
        return normalized

    async def resolve_for_runtime(self, user_id: str, refs: list[dict] | None) -> list[dict]:
        """Enabled, owned skills (pinned or latest version). Missing/disabled/foreign ones are skipped silently —
        a chat turn must never fail because a skill was deleted."""
        out: list[dict] = []
        try:
            parsed = [parse_skill_ref(r) for r in (refs or [])]
        except (KeyError, ValueError, TypeError):
            return out
        skills = {s.id: s for s in await self.repo.get_by_ids(user_id, [sid for sid, _ in parsed])}
        wanted = [(sid, v or skills[sid].latest_version) for sid, v in parsed if sid in skills and skills[sid].is_enabled]
        summaries = await self.repo.version_summaries(wanted)
        for skill_id, version in wanted:
            row = summaries.get((skill_id, version))
            if row is None:
                continue
            out.append({
                "skill_id": str(skill_id), "name": skills[skill_id].name, "description": row.description,
                "version": version, "version_id": str(row.id), "has_scripts": bool(row.has_scripts),
            })
            if len(out) >= settings.SKILLS_MAX_PER_AGENT:
                break
        return out

    async def record_usage(
        self, *, skill_id: str, version: int, user_id: str, conversation_id: str,
        agent_id: str | None, action: str, detail: str | None = None,
    ) -> None:
        self.repo.add_usage(
            skill_id=uuid.UUID(skill_id), version=version, user_id=user_id, conversation_id=conversation_id,
            agent_id=uuid.UUID(agent_id) if agent_id else None, action=action, detail=(detail or None) and detail[:512],
        )
        await self.repo.commit()


async def agents_referencing(db: AsyncSession, user_id: str, skill_id: uuid.UUID) -> list[Agent]:
    return [
        a for a in await AgentRepo(db).list_for_user(user_id)
        if any(str(ref.get("skill_id")) == str(skill_id) for ref in a.skill_ids or [])
    ]
