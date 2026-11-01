"""
Agent skills: a Skill is a named, per-user package of instructions (SKILL.md) plus
optional reference files and scripts. Versions are immutable — editing creates N+1;
agents reference skills by {skill_id, version|null} (null = follow latest).
See app/skills/ for parsing/validation and the tools that expose skills to the model.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_skills_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    # slug, unique per user: ^[a-z0-9][a-z0-9-]{1,62}$
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # copy of the latest version's description, for listings
    description: Mapped[str] = mapped_column(Text, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan", order_by="SkillVersion.version"
    )


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    # SKILL.md without frontmatter (<= SKILLS_MAX_BODY_KB). Kept in Postgres: it is read on every skill_load.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    frontmatter: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    has_scripts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # sha256 of the normalized package; an identical re-upload returns the existing version
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    skill: Mapped[Skill] = relationship(back_populates="versions")
    files: Mapped[list["SkillFile"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SkillFile.path"
    )


class SkillFile(Base):
    __tablename__ = "skill_files"
    __table_args__ = (UniqueConstraint("skill_version_id", "path", name="uq_skill_files_version_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)  # normalized, e.g. "references/format.md"
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    version: Mapped[SkillVersion] = relationship(back_populates="files")


class SkillUsage(Base):
    """Audit/analytics: which skill was loaded/read/run, in which conversation."""

    __tablename__ = "skill_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # load | read | run
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)  # file path / script name
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
