"""Request/response schemas for the REST API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    language: Literal["python"] = "python"


class SessionOut(BaseModel):
    id: uuid.UUID
    conversation_id: str
    user_id: str
    language: str
    status: str
    created_at: datetime
    last_used_at: datetime
    terminated_at: datetime | None
    terminate_reason: str | None


class ExecutionCreate(BaseModel):
    code: str
    timeout_seconds: int | None = None


class Artifact(BaseModel):
    name: str
    kind: str
    size: int | None = None
    key: str | None = None
    url: str | None = None
    content_type: str | None = None
    error: str | None = None


class ExecutionOut(BaseModel):
    execution_id: uuid.UUID
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    truncated: bool
    timed_out: bool
    oom_killed: bool
    duration_ms: int
    workspace_reset: bool
    sandbox_restarted: bool
    artifacts: list[Artifact]


class FileWrite(BaseModel):
    path: str
    content: str


class FileEntry(BaseModel):
    path: str
    type: str
    size: int
    mtime: int


class FileContent(BaseModel):
    path: str
    content: str
    truncated: bool


class SkillFileIn(BaseModel):
    path: str
    content_base64: str


class SkillImportCreate(BaseModel):
    name: str
    files: list[SkillFileIn] = Field(min_length=1, max_length=200)


class SkillImportOut(BaseModel):
    path: str
    files: int
    size: int


class ImportCreate(BaseModel):
    file_id: str


class ImportOut(BaseModel):
    path: str
    size: int
    filename: str
