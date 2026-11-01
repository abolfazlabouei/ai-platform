"""
Skill package parsing + validation. This is the main attack surface of the feature
(untrusted archives), so every check from the plan lives here and is unit-tested:

  zip slip / absolute paths / backslashes / NUL / non-UTF-8 names, symlinks and
  special files, encrypted entries, duplicate normalized paths, too many entries,
  zip bombs (bytes are counted while streaming — declared sizes are never trusted),
  disallowed file types, oversized assets.

Three input forms produce the same `SkillPackage`: a .zip, a single SKILL.md text,
or JSON {skill_md, files}. Text is normalized to LF and files are sorted, so the
checksum is stable and an identical re-upload maps to the existing version.
"""
from __future__ import annotations

import hashlib
import io
import posixpath
import stat
import zipfile
from dataclasses import dataclass, field

from app.core.config import Settings, settings as default_settings
from app.skills.errors import SkillValidationError
from app.skills.frontmatter import parse_skill_md

SKILL_MD = "SKILL.md"
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".sh", ".html", ".sql"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".xlsx", ".docx"}
_MIMES = {
    ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv", ".json": "application/json",
    ".yaml": "text/yaml", ".yml": "text/yaml", ".py": "text/x-python", ".js": "text/javascript",
    ".sh": "text/x-shellscript", ".html": "text/html", ".sql": "application/sql",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_IGNORED_PARTS = {"__MACOSX", ".git"}
_IGNORED_NAMES = {".DS_Store", "Thumbs.db"}
_CHUNK = 64 * 1024


@dataclass
class PackageFile:
    path: str
    data: bytes
    mime: str
    is_text: bool

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class SkillPackage:
    name: str
    description: str
    body: str
    frontmatter: dict
    files: list[PackageFile]  # includes SKILL.md; sorted by path
    warnings: list[str] = field(default_factory=list)

    @property
    def has_scripts(self) -> bool:
        return any(f.path.startswith("scripts/") for f in self.files)

    @property
    def total_bytes(self) -> int:
        return sum(len(f.data) for f in self.files)

    @property
    def checksum(self) -> str:
        digest = hashlib.sha256()
        for f in self.files:  # already sorted
            digest.update(f"{f.path}\0{f.sha256}\n".encode())
        return digest.hexdigest()


def normalize_path(raw: str) -> str:
    """Validated relative POSIX path, or SkillValidationError. Never returns '..' or absolute paths."""
    if not isinstance(raw, str) or not raw:
        raise SkillValidationError("empty file path")
    if "\x00" in raw:
        raise SkillValidationError("file path contains a NUL byte")
    if "\\" in raw:
        raise SkillValidationError(f"backslashes are not allowed in paths: {raw!r}")
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError:
        raise SkillValidationError("file path is not valid UTF-8") from None
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise SkillValidationError(f"absolute paths are not allowed: {raw!r}")
    parts = raw.split("/")
    if any(p == ".." for p in parts):
        raise SkillValidationError(f"'..' is not allowed in paths: {raw!r}")
    normalized = posixpath.normpath(raw)
    if normalized in (".", "") or normalized.startswith(".."):
        raise SkillValidationError(f"invalid file path: {raw!r}")
    if len(normalized) > 512:
        raise SkillValidationError("file path is too long")
    return normalized


def _ignored(path: str) -> bool:
    parts = path.split("/")
    return bool(_IGNORED_PARTS & set(parts)) or parts[-1] in _IGNORED_NAMES


def _build_file(path: str, data: bytes, cfg: Settings) -> PackageFile:
    ext = posixpath.splitext(path)[1].lower()
    if ext in TEXT_EXTENSIONS:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise SkillValidationError(f"{path}: text files must be UTF-8") from None
        data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        is_text = True
    elif ext in ASSET_EXTENSIONS:
        is_text = False
    else:
        allowed = sorted(TEXT_EXTENSIONS | ASSET_EXTENSIONS)
        raise SkillValidationError(f"{path}: file type '{ext or '(none)'}' is not allowed (allowed: {', '.join(allowed)})")
    if len(data) > cfg.SKILLS_MAX_ASSET_MB * 1024 * 1024:
        raise SkillValidationError(f"{path}: larger than {cfg.SKILLS_MAX_ASSET_MB} MB")
    return PackageFile(path=path, data=data, mime=_MIMES[ext], is_text=is_text)


def assemble(raw_files: dict[str, bytes], cfg: Settings) -> SkillPackage:
    if SKILL_MD not in raw_files:
        raise SkillValidationError("SKILL.md was not found at the package root")
    if len(raw_files) > cfg.SKILLS_MAX_FILES:
        raise SkillValidationError(f"too many files ({len(raw_files)}, max {cfg.SKILLS_MAX_FILES})")

    files = [_build_file(path, data, cfg) for path, data in raw_files.items()]
    files.sort(key=lambda f: f.path)
    skill_md = next(f for f in files if f.path == SKILL_MD)
    parsed = parse_skill_md(skill_md.data.decode("utf-8"))

    warnings = list(parsed.warnings)
    total = sum(len(f.data) for f in files)
    if total > cfg.SKILLS_MAX_UNCOMPRESSED_MB * 1024 * 1024:
        raise SkillValidationError(f"package is larger than {cfg.SKILLS_MAX_UNCOMPRESSED_MB} MB uncompressed")
    return SkillPackage(
        name=parsed.name, description=parsed.description, body=parsed.body, frontmatter=parsed.frontmatter,
        files=files, warnings=warnings,
    )


def _strip_single_root(raw: dict[str, bytes]) -> dict[str, bytes]:
    """`monthly-report/SKILL.md` + `monthly-report/refs/a.md` -> `SKILL.md` + `refs/a.md`."""
    if SKILL_MD in raw:
        return raw
    roots = {p.split("/", 1)[0] for p in raw if "/" in p}
    if len(roots) == 1 and all(p.startswith(next(iter(roots)) + "/") for p in raw):
        root = next(iter(roots))
        return {p[len(root) + 1:]: d for p, d in raw.items()}
    return raw


def parse_zip(data: bytes, cfg: Settings | None = None) -> SkillPackage:
    cfg = cfg or default_settings
    if len(data) > cfg.SKILLS_MAX_ZIP_MB * 1024 * 1024:
        raise SkillValidationError(f"zip is larger than {cfg.SKILLS_MAX_ZIP_MB} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SkillValidationError("the upload is not a valid zip file") from None

    infos = [i for i in archive.infolist()]
    if len(infos) > cfg.SKILLS_MAX_FILES + 50:  # directory entries / ignored junk get some slack
        raise SkillValidationError(f"zip has too many entries ({len(infos)})")

    budget = cfg.SKILLS_MAX_UNCOMPRESSED_MB * 1024 * 1024
    spent = 0
    raw: dict[str, bytes] = {}
    for info in infos:
        name = info.filename
        if info.is_dir():
            if name.rstrip("/"):
                normalize_path(name.rstrip("/"))  # directory entries must not escape either
            continue
        path = normalize_path(name)
        if _ignored(path):
            continue
        mode = info.external_attr >> 16
        if mode and (stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_IFMT(mode) == 0)):
            raise SkillValidationError(f"{path}: symlinks and special files are not allowed")
        if info.flag_bits & 0x1:
            raise SkillValidationError(f"{path}: encrypted entries are not supported")
        if path in raw:
            raise SkillValidationError(f"duplicate path in zip: {path}")
        # Never trust declared sizes: count real bytes while streaming (zip bombs lie in headers).
        chunks, size = [], 0
        try:
            with archive.open(info) as handle:
                while chunk := handle.read(_CHUNK):
                    size += len(chunk)
                    spent += len(chunk)
                    if spent > budget:
                        raise SkillValidationError(
                            f"package is larger than {cfg.SKILLS_MAX_UNCOMPRESSED_MB} MB uncompressed"
                        )
                    chunks.append(chunk)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
            raise SkillValidationError(f"{path}: cannot be read from the zip ({type(exc).__name__})") from None
        raw[path] = b"".join(chunks)

    return assemble(_strip_single_root(raw), cfg)


def parse_skill_md_only(text: str, cfg: Settings | None = None) -> SkillPackage:
    cfg = cfg or default_settings
    return assemble({SKILL_MD: text.encode("utf-8")}, cfg)


def parse_json(skill_md: str, files: dict[str, str] | None, cfg: Settings | None = None) -> SkillPackage:
    """Small text-only skills: SKILL.md text plus {path: text}."""
    cfg = cfg or default_settings
    raw: dict[str, bytes] = {SKILL_MD: skill_md.encode("utf-8")}
    for path, content in (files or {}).items():
        normalized = normalize_path(path)
        if normalized == SKILL_MD:
            raise SkillValidationError("SKILL.md goes in 'skill_md', not in 'files'")
        if normalized in raw:
            raise SkillValidationError(f"duplicate path: {normalized}")
        raw[normalized] = content.encode("utf-8")
    return assemble(raw, cfg)


def build_zip(package_files: list[tuple[str, bytes]]) -> bytes:
    """Zip of (path, bytes) for download; paths are stored exactly as validated."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in package_files:
            archive.writestr(zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
