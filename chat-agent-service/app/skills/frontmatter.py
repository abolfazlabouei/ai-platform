"""
SKILL.md parsing: YAML frontmatter between leading `---` lines, then a markdown body.

Only `yaml.safe_load` is ever used (a `!!python/object` tag must fail, not execute).
`name` and `description` are required; unknown keys are kept in the stored frontmatter
but are NEVER honored (e.g. `allowed-tools` grants nothing — a skill can only use tools
the agent already has).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from app.core.config import settings
from app.skills.errors import SkillValidationError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 1024
# The description is the trigger: it should say WHEN to use the skill (English or Persian cues).
_WHEN_RE = re.compile(r"\b(use when|when|if the user|whenever)\b|وقتی|زمانی|هنگام|در صورتی|هرگاه|برای", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)


@dataclass
class ParsedSkillMd:
    name: str
    description: str
    body: str
    frontmatter: dict
    warnings: list[str] = field(default_factory=list)


def parse_skill_md(text: str) -> ParsedSkillMd:
    errors: list[str] = []
    match = _FRONTMATTER_RE.match(text or "")
    if not match:
        raise SkillValidationError("SKILL.md must start with a YAML frontmatter block between '---' lines")
    raw_yaml, body = match.group(1), match.group(2)

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"SKILL.md frontmatter is not valid YAML: {str(exc).splitlines()[0]}") from None
    if not isinstance(data, dict):
        raise SkillValidationError("SKILL.md frontmatter must be a YAML mapping with 'name' and 'description'")

    name, description = data.get("name"), data.get("description")
    if not isinstance(name, str) or not name:
        errors.append("frontmatter 'name' is required (a string)")
    elif not NAME_RE.match(name):
        errors.append("frontmatter 'name' must be a slug: lowercase letters, digits and '-', 2-63 chars, starting with a letter or digit")
    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter 'description' is required (a string)")
    else:
        description = description.strip()
        if len(description) < DESCRIPTION_MIN:
            errors.append(f"'description' is too short ({len(description)} chars); say what the skill does and when to use it (min {DESCRIPTION_MIN})")
        elif len(description) > DESCRIPTION_MAX:
            errors.append(f"'description' is too long ({len(description)} chars, max {DESCRIPTION_MAX})")
        if "\n\n" in description.replace("\r\n", "\n"):
            errors.append("'description' must be a single paragraph (no blank lines)")

    body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if len(body.encode("utf-8")) > settings.SKILLS_MAX_BODY_KB * 1024:
        errors.append(f"the SKILL.md body is larger than {settings.SKILLS_MAX_BODY_KB} KB; move detail into references/ files")
    if not body.strip():
        errors.append("the SKILL.md body is empty; write the instructions after the frontmatter")
    if errors:
        raise SkillValidationError(errors)

    warnings: list[str] = []
    if not _WHEN_RE.search(description):
        warnings.append(
            "the description does not say WHEN to use the skill; the description is what makes the agent pick it "
            "(e.g. 'Use when the user asks for ...')"
        )
    return ParsedSkillMd(
        name=name, description=" ".join(description.split()), body=body, frontmatter=json.loads(json.dumps(data, default=str)), warnings=warnings
    )
