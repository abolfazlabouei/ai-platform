"""SKILL.md frontmatter + package validation, including the archive attack surface."""
import pytest

from app.core.config import Settings
from app.skills import package as pkg
from app.skills.errors import SkillValidationError
from app.skills.frontmatter import parse_skill_md
from tests.skill_helpers import GOOD_MD, make_zip, skill_md


# ---------------- frontmatter ----------------


def test_valid_skill_md():
    parsed = parse_skill_md(GOOD_MD)
    assert parsed.name == "monthly-report"
    assert parsed.body.startswith("# Monthly report")
    assert parsed.warnings == []


@pytest.mark.parametrize(
    "text, message",
    [
        ("no frontmatter at all", "frontmatter"),
        ("---\ndescription: Does a thing when the user asks for it.\n---\nbody", "'name' is required"),
        ("---\nname: ok-name\n---\nbody", "'description' is required"),
        (skill_md(name="Bad Name"), "slug"),
        (skill_md(name="a"), "slug"),
        (skill_md(name="-leading"), "slug"),
        (skill_md(description="too short"), "too short"),
        (skill_md(description="x" * 1025), "too long"),
        ("---\nname: [unclosed\ndescription: x\n---\nbody", "not valid YAML"),
        ("---\n- just\n- a list\n---\nbody", "mapping"),
        (skill_md(body="   \n"), "body is empty"),
    ],
)
def test_invalid_frontmatter(text, message):
    with pytest.raises(SkillValidationError) as info:
        parse_skill_md(text)
    assert any(message in e for e in info.value.errors), info.value.errors


def test_yaml_python_object_tag_is_rejected_not_executed():
    evil = "---\nname: evil-skill\ndescription: !!python/object/apply:os.system ['echo pwned']\n---\nbody"
    with pytest.raises(SkillValidationError):
        parse_skill_md(evil)


def test_description_must_be_one_paragraph():
    text = "---\nname: two-paras\ndescription: |\n  First paragraph is long enough.\n\n  Second paragraph.\n---\nbody"
    with pytest.raises(SkillValidationError, match="single paragraph"):
        parse_skill_md(text)


def test_warns_when_description_does_not_say_when():
    parsed = parse_skill_md(skill_md(description="A monthly report generator for the clinic staff."))
    assert any("WHEN" in w for w in parsed.warnings)


def test_persian_when_cue_counts():
    parsed = parse_skill_md(skill_md(description="گزارش ماهانهٔ کلینیک را می‌نویسد؛ وقتی کاربر گزارش ماهانه می‌خواهد."))
    assert parsed.warnings == []


def test_unknown_keys_kept_but_json_safe():
    parsed = parse_skill_md(skill_md(extra="allowed-tools: [run_python]\nreleased: 2026-01-02\n"))
    assert parsed.frontmatter["allowed-tools"] == ["run_python"]
    assert parsed.frontmatter["released"] == "2026-01-02"  # a YAML date became a JSON-safe string


def test_body_size_limit():
    cfg_kb = Settings().SKILLS_MAX_BODY_KB
    with pytest.raises(SkillValidationError, match="larger than"):
        parse_skill_md(skill_md(body="x" * (cfg_kb * 1024 + 1)))


# ---------------- zip ----------------


def test_valid_zip_with_references():
    package = pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "references/format.md": "# Format\r\nline\r\n"}))
    assert package.name == "monthly-report"
    assert [f.path for f in package.files] == ["SKILL.md", "references/format.md"]
    assert package.files[1].data == b"# Format\nline\n"  # CRLF normalized
    assert not package.has_scripts


def test_nested_single_root_folder_is_stripped():
    package = pkg.parse_zip(make_zip({"monthly-report/SKILL.md": GOOD_MD, "monthly-report/references/a.md": "a"}))
    assert [f.path for f in package.files] == ["SKILL.md", "references/a.md"]


def test_macos_junk_is_ignored():
    package = pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "__MACOSX/._SKILL.md": "x", ".DS_Store": "x"}))
    assert [f.path for f in package.files] == ["SKILL.md"]


def test_scripts_flag():
    package = pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "scripts/summarize.py": "print(1)"}))
    assert package.has_scripts


@pytest.mark.parametrize("name", ["../evil.md", "a/../../evil.md", "/abs/evil.md", "C:/evil.md", "a\\b.md"])
def test_zip_slip_and_bad_paths_rejected(name):
    with pytest.raises(SkillValidationError):
        pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, name: "x"}))


def test_traversing_directory_entry_rejected():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("SKILL.md", GOOD_MD)
        zf.writestr(zipfile.ZipInfo("../outside/"), b"")
    with pytest.raises(SkillValidationError):
        pkg.parse_zip(buffer.getvalue())


def test_symlink_entry_rejected():
    with pytest.raises(SkillValidationError, match="symlinks"):
        pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD}, symlinks={"references/passwd": "/etc/passwd"}))


def test_zip_bomb_rejected_by_counting_real_bytes():
    cfg = Settings(SKILLS_MAX_UNCOMPRESSED_MB=2, SKILLS_MAX_ASSET_MB=5)
    bomb = make_zip({"SKILL.md": GOOD_MD, "references/zeros.txt": b"\0" * (4 * 1024 * 1024)})
    assert len(bomb) < 100 * 1024  # tiny on the wire, huge when expanded
    with pytest.raises(SkillValidationError, match="uncompressed"):
        pkg.parse_zip(bomb, cfg)


def test_too_many_files():
    cfg = Settings(SKILLS_MAX_FILES=3)
    entries = {"SKILL.md": GOOD_MD, **{f"references/{i}.md": "x" for i in range(5)}}
    with pytest.raises(SkillValidationError, match="too many"):
        pkg.parse_zip(make_zip(entries), cfg)


def test_oversized_zip_upload():
    with pytest.raises(SkillValidationError, match="zip is larger"):
        pkg.parse_zip(b"0" * (Settings().SKILLS_MAX_ZIP_MB * 1024 * 1024 + 1))


def test_not_a_zip():
    with pytest.raises(SkillValidationError, match="not a valid zip"):
        pkg.parse_zip(b"definitely not a zip")


def test_missing_skill_md():
    with pytest.raises(SkillValidationError, match="SKILL.md was not found"):
        pkg.parse_zip(make_zip({"references/a.md": "x"}))


def test_disallowed_file_type():
    with pytest.raises(SkillValidationError, match="not allowed"):
        pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "bin/tool.exe": b"MZ"}))


def test_non_utf8_text_rejected():
    with pytest.raises(SkillValidationError, match="UTF-8"):
        pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "references/a.md": b"\xff\xfe\x00bad"}))


def test_oversized_asset():
    cfg = Settings(SKILLS_MAX_ASSET_MB=1)
    with pytest.raises(SkillValidationError, match="larger than 1 MB"):
        pkg.parse_zip(make_zip({"SKILL.md": GOOD_MD, "assets/big.png": b"\0" * (2 * 1024 * 1024)}), cfg)


def test_duplicate_paths_rejected():
    import io
    import warnings
    import zipfile

    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about duplicate names
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("SKILL.md", GOOD_MD)
            zf.writestr("references/a.md", "one")
            zf.writestr("references/a.md", "two")
    with pytest.raises(SkillValidationError, match="duplicate"):
        pkg.parse_zip(buffer.getvalue())


@pytest.mark.parametrize("bad", ["", "a\x00b", "..", "a/../b", "/x", "x\\y", "D:/x"])
def test_normalize_path_rejects(bad):
    with pytest.raises(SkillValidationError):
        pkg.normalize_path(bad)


def test_normalize_path_accepts_and_collapses():
    assert pkg.normalize_path("references/./a.md") == "references/a.md"
    assert pkg.normalize_path("گزارش/فرمت.md") == "گزارش/فرمت.md"


# ---------------- json / single file ----------------


def test_json_package():
    package = pkg.parse_json(GOOD_MD, {"references/format.md": "# F"})
    assert [f.path for f in package.files] == ["SKILL.md", "references/format.md"]


def test_json_rejects_skill_md_in_files_and_traversal():
    with pytest.raises(SkillValidationError):
        pkg.parse_json(GOOD_MD, {"SKILL.md": "x"})
    with pytest.raises(SkillValidationError):
        pkg.parse_json(GOOD_MD, {"../x.md": "x"})


def test_checksum_is_stable_and_content_sensitive():
    a = pkg.parse_json(GOOD_MD, {"references/b.md": "1", "references/a.md": "2"})
    b = pkg.parse_json(GOOD_MD.replace("\n", "\r\n"), {"references/a.md": "2", "references/b.md": "1"})
    c = pkg.parse_json(GOOD_MD, {"references/a.md": "2", "references/b.md": "CHANGED"})
    assert a.checksum == b.checksum  # order and line endings do not matter
    assert a.checksum != c.checksum
