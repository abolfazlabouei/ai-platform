from __future__ import annotations


class SkillValidationError(Exception):
    """The uploaded package/SKILL.md is invalid. `errors` are user-facing (shown in the UI)."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


class SkillNotFound(Exception):
    pass


class SkillConflict(Exception):
    """A skill with this name already exists (use update)."""
