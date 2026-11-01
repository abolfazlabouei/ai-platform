"""Request/response schemas for /skills and the skill references used by agents and chat."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SkillRef(BaseModel):
    """How an agent / chat request attaches a skill. version=None follows the skill's latest version."""

    skill_id: uuid.UUID
    version: int | None = Field(default=None, ge=1)


class SkillJsonIn(BaseModel):
    """Small text-only skills: SKILL.md text plus {path: text} for other files."""

    skill_md: str
    files: dict[str, str] = Field(default_factory=dict)


class SkillEditIn(SkillJsonIn):
    """New version from the latest: `files` add/replace text files, `remove` drops paths, the rest carries over."""

    remove: list[str] = Field(default_factory=list)


class SkillPatch(BaseModel):
    is_enabled: bool


class SkillFileOut(BaseModel):
    path: str
    size_bytes: int
    mime: str


class SkillVersionOut(BaseModel):
    version: int
    description: str
    has_scripts: bool
    total_bytes: int
    created_by: str
    created_at: datetime


class SkillVersionDetail(SkillVersionOut):
    body: str
    frontmatter: dict
    files: list[SkillFileOut]


class SkillSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    latest_version: int
    has_scripts: bool
    is_enabled: bool
    used_by_agents: int
    created_at: datetime
    updated_at: datetime


class SkillDetail(SkillSummary):
    versions: list[SkillVersionOut]
    latest: SkillVersionDetail


class SkillSaveResult(BaseModel):
    skill: SkillSummary
    version: int
    created_version: bool  # False: an identical package already existed, nothing new was stored
    warnings: list[str]


class SkillValidation(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    name: str | None = None
    description: str | None = None
    has_scripts: bool = False
    files: list[SkillFileOut] = Field(default_factory=list)


class SkillFileContent(BaseModel):
    path: str
    mime: str
    size_bytes: int
    is_text: bool
    content: str | None = None  # text files
    url: str | None = None  # binary files: short-lived presigned link
