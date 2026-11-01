"""Builders for skill packages used across the skill tests."""
import io
import zipfile

GOOD_MD = """---
name: monthly-report
description: Write the clinic's monthly performance report in the standard format. Use when the user asks for a monthly or periodic summary of clinic performance.
---
# Monthly report
1. Collect the numbers.
2. Follow references/format.md for the layout.
"""


def skill_md(name="monthly-report", description=None, body="# Steps\nDo the thing.\n", extra=""):
    description = description or f"Do the {name} task for the clinic. Use when the user asks for {name}."
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}"


def make_zip(entries: dict[str, bytes | str], *, symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries.items():
            zf.writestr(path, data if isinstance(data, bytes) else data.encode())
        for path, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(path)
            info.external_attr = (0o120777 << 16)  # S_IFLNK | 0777
            zf.writestr(info, target)
    return buffer.getvalue()
