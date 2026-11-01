"""
/skills — upload (zip or JSON), validate, version, list, edit, enable/disable, download, delete.

All routes are scoped to the caller (`require_user`); another user's skill is a 404.
Validation failures are 422 {"detail": "...", "errors": [...]}.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.models.skill import Skill, SkillVersion
from app.schemas.skill import (
    SkillDetail, SkillEditIn, SkillFileContent, SkillFileOut, SkillJsonIn, SkillPatch, SkillSaveResult,
    SkillSummary, SkillValidation, SkillVersionDetail, SkillVersionOut,
)
from app.services.skill_service import SaveResult, SkillService
from app.skills import package as pkg
from app.skills.errors import SkillNotFound, SkillValidationError

router = APIRouter(prefix="/skills", tags=["skills"])

_TEXT_PREVIEW_MAX = 256 * 1024


def _summary(skill: Skill, has_scripts: bool, used_by_agents: int) -> SkillSummary:
    return SkillSummary(
        id=skill.id, name=skill.name, description=skill.description, latest_version=skill.latest_version,
        has_scripts=has_scripts, is_enabled=skill.is_enabled, used_by_agents=used_by_agents,
        created_at=skill.created_at, updated_at=skill.updated_at,
    )


def _version_out(v: SkillVersion) -> SkillVersionOut:
    return SkillVersionOut(
        version=v.version, description=v.description, has_scripts=v.has_scripts, total_bytes=v.total_bytes,
        created_by=v.created_by, created_at=v.created_at,
    )


def _version_detail(v: SkillVersion) -> SkillVersionDetail:
    return SkillVersionDetail(
        **_version_out(v).model_dump(), body=v.body, frontmatter=v.frontmatter,
        files=[SkillFileOut(path=f.path, size_bytes=f.size_bytes, mime=f.mime) for f in v.files],
    )


def _saved(result: SaveResult) -> SkillSaveResult:
    return SkillSaveResult(
        skill=_summary(result.skill, result.version.has_scripts, 0), version=result.version.version,
        created_version=result.created_version, warnings=result.warnings,
    )


async def _read_package(request: Request) -> pkg.SkillPackage:
    """multipart (zip upload) or JSON ({skill_md, files}) -> validated package."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) and not hasattr(upload, "read"):
            raise SkillValidationError("multipart upload needs a 'file' field with the .zip")
        limit = settings.SKILLS_MAX_ZIP_MB * 1024 * 1024
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise SkillValidationError(f"zip is larger than {settings.SKILLS_MAX_ZIP_MB} MB")
        name = (getattr(upload, "filename", "") or "").lower()
        if name.endswith(".md"):
            return pkg.parse_skill_md_only(data.decode("utf-8", errors="strict"))
        return pkg.parse_zip(data)
    try:
        body = SkillJsonIn.model_validate(await request.json())
    except Exception:  # noqa: BLE001
        raise SkillValidationError("send a .zip as multipart 'file', or JSON {skill_md, files}") from None
    return pkg.parse_json(body.skill_md, body.files)


@router.post("/validate", response_model=SkillValidation)
async def validate_skill(request: Request, user: CurrentUser = Depends(require_user)):
    """Dry run for the UI: never stores anything and never 422s on package problems."""
    try:
        package = await _read_package(request)
    except SkillValidationError as exc:
        return SkillValidation(valid=False, errors=exc.errors, warnings=[])
    return SkillValidation(
        valid=True, errors=[], warnings=package.warnings, name=package.name, description=package.description,
        has_scripts=package.has_scripts,
        files=[SkillFileOut(path=f.path, size_bytes=len(f.data), mime=f.mime) for f in package.files],
    )


@router.post("", response_model=SkillSaveResult)
async def create_skill(
    request: Request, update: bool = Query(False), user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    package = await _read_package(request)
    result = await SkillService(db).save_package(user.user_id, package, update=update)
    return _saved(result)


@router.get("", response_model=list[SkillSummary])
async def list_skills(user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    rows = await SkillService(db).list_with_usage(user.user_id)
    return [_summary(r["skill"], r["has_scripts"], r["used_by_agents"]) for r in rows]


@router.get("/{skill_id}", response_model=SkillDetail)
async def get_skill(skill_id: uuid.UUID, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    service = SkillService(db)
    skill = await service.get_owned(user.user_id, skill_id)
    latest = await service.get_version(skill)
    versions = await service.repo.list_versions(skill.id)
    used = next((r["used_by_agents"] for r in await service.list_with_usage(user.user_id) if r["skill"].id == skill.id), 0)
    return SkillDetail(
        **_summary(skill, latest.has_scripts, used).model_dump(),
        versions=[_version_out(v) for v in versions], latest=_version_detail(latest),
    )


@router.get("/{skill_id}/versions/{version}", response_model=SkillVersionDetail)
async def get_skill_version(
    skill_id: uuid.UUID, version: int, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    service = SkillService(db)
    skill = await service.get_owned(user.user_id, skill_id)
    return _version_detail(await service.get_version(skill, version))


@router.get("/{skill_id}/versions/{version}/files", response_model=SkillFileContent)
async def get_skill_file(
    skill_id: uuid.UUID, version: int, path: str = Query(...),
    user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    service = SkillService(db)
    skill = await service.get_owned(user.user_id, skill_id)
    row = await service.get_version(skill, version)
    entry = next((f for f in row.files if f.path == path), None)
    if entry is None:
        raise SkillNotFound(f"file '{path}' not found in this skill")
    if entry.mime.startswith("text/") or entry.mime in ("application/json", "application/sql"):
        data, _ = await service.read_file(row, path)
        return SkillFileContent(
            path=path, mime=entry.mime, size_bytes=entry.size_bytes, is_text=True,
            content=data[:_TEXT_PREVIEW_MAX].decode("utf-8", errors="ignore"),
        )
    return SkillFileContent(
        path=path, mime=entry.mime, size_bytes=entry.size_bytes, is_text=False,
        url=await service.storage.presign(entry.storage_key),
    )


@router.put("/{skill_id}", response_model=SkillSaveResult)
async def edit_skill(
    skill_id: uuid.UUID, body: SkillEditIn, user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = SkillService(db)
    skill = await service.get_owned(user.user_id, skill_id)
    return _saved(await service.edit(user.user_id, skill, body.skill_md, body.files, body.remove))


@router.patch("/{skill_id}", response_model=SkillSummary)
async def patch_skill(
    skill_id: uuid.UUID, body: SkillPatch, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    service = SkillService(db)
    skill = await service.set_enabled(await service.get_owned(user.user_id, skill_id), body.is_enabled)
    latest = await service.get_version(skill)
    used = next((r["used_by_agents"] for r in await service.list_with_usage(user.user_id) if r["skill"].id == skill.id), 0)
    return _summary(skill, latest.has_scripts, used)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: uuid.UUID, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    service = SkillService(db)
    await service.delete(user.user_id, await service.get_owned(user.user_id, skill_id))


@router.get("/{skill_id}/download")
async def download_skill(
    skill_id: uuid.UUID, version: int | None = Query(None), user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = SkillService(db)
    skill = await service.get_owned(user.user_id, skill_id)
    row = await service.get_version(skill, version)
    data = await service.build_download(row)
    return Response(
        data, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}-v{row.version}.zip"'},
    )
