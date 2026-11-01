"""
Level 1 of progressive disclosure: the compact catalog placed in the system prompt.
Only `name` + `description` of each skill — never bodies. The description is the
trigger, so it is kept whole; the overall budget is enforced by dropping skills
(listed in a note) rather than truncating a description mid-sentence.
"""
from __future__ import annotations

from app.core.config import settings

SKILL_LOAD_TOOL = "skill_load"
SKILL_READ_FILE_TOOL = "skill_read_file"
SKILL_RUN_SCRIPT_TOOL = "skill_run_script"

_PREAMBLE = (
    "## Skills\n"
    "You have skills: packaged instructions for specific kinds of tasks. Before doing a task that matches a "
    f"skill's description, call {SKILL_LOAD_TOOL} with its name and follow the instructions it returns. "
    "Only load skills that are relevant; do not mention skills to the user unless asked."
)


def _clean(text: str) -> str:
    # keep user-authored text from closing/opening the <skills> block
    return " ".join(text.split()).replace("<", "(").replace(">", ")")


def build_catalog(skills: list[dict], max_chars: int | None = None) -> str:
    """`skills`: [{"name", "description", ...}]. Returns "" when there are none."""
    if not skills:
        return ""
    budget = max_chars if max_chars is not None else settings.SKILLS_CATALOG_MAX_CHARS
    lines: list[str] = []
    used = len(_PREAMBLE) + 40
    omitted: list[str] = []
    for skill in skills:
        line = f"- {_clean(skill['name'])}: {_clean(skill['description'])}"
        if used + len(line) + 1 > budget:
            omitted.append(skill["name"])
            continue
        lines.append(line)
        used += len(line) + 1
    block = f"{_PREAMBLE}\n\n<skills>\n" + "\n".join(lines) + "\n</skills>"
    if omitted:
        block += f"\n(Not listed because of the prompt budget: {', '.join(_clean(n) for n in omitted)}.)"
    return block
