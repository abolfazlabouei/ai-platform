import pytest

from app.sandbox.files import PathError, parse_listing, resolve_workspace_path, sanitize_filename


@pytest.mark.parametrize(
    "path, expected",
    [
        ("data.csv", "/workspace/data.csv"),
        ("inputs/report.xlsx", "/workspace/inputs/report.xlsx"),
        ("./outputs/chart.png", "/workspace/outputs/chart.png"),
        ("/workspace/a/b.txt", "/workspace/a/b.txt"),
        ("a//b.txt", "/workspace/a/b.txt"),
        ("گزارش.txt", "/workspace/گزارش.txt"),
    ],
)
def test_accepts_workspace_paths(path, expected):
    assert resolve_workspace_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "a/../../etc/passwd",
        "/etc/passwd",
        "/workspace/../etc/passwd",
        "/workspacex/file",
        "/workspace",
        ".",
        "",
        "   ",
        "a\x00b",
        "..\\..\\etc\\passwd",
    ],
)
def test_rejects_escapes(path):
    with pytest.raises(PathError):
        resolve_workspace_path(path)


def test_percent_encoded_traversal_is_not_decoded():
    # We never URL-decode, so this is a literal directory name under /workspace.
    assert resolve_workspace_path("inputs/%2e%2e/x") == "/workspace/inputs/%2e%2e/x"


def test_root_allowed_only_for_listing():
    assert resolve_workspace_path(".", allow_root=True) == "/workspace"
    assert resolve_workspace_path("/workspace", allow_root=True) == "/workspace"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("report.xlsx", "report.xlsx"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\file.docx", "file.docx"),
        ("..", "document"),
        ("", "document"),
        ("a\x00b.txt", "ab.txt"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_parse_listing():
    raw = b"d\t0\t100\toutputs\nf\t12\t101\toutputs/a.png\nl\t9\t102\tlink\ngarbage\n"
    assert parse_listing(raw) == [
        {"path": "outputs", "type": "dir", "size": 0, "mtime": 100},
        {"path": "outputs/a.png", "type": "file", "size": 12, "mtime": 101},
        {"path": "link", "type": "symlink", "size": 9, "mtime": 102},
    ]


# ---- skill import paths ----

from app.sandbox.files import resolve_skill_path  # noqa: E402


def test_skill_paths_stay_inside_the_skill_folder():
    assert resolve_skill_path("monthly-report", "scripts/summarize.py") == "/workspace/skills/monthly-report/scripts/summarize.py"
    for rel in ["../other/x.py", "scripts/../../other/x.py", "/etc/passwd", "a\\b.py", "", "a\x00b"]:
        with pytest.raises(PathError):
            resolve_skill_path("monthly-report", rel)


@pytest.mark.parametrize("name", ["", "Bad Name", "../x", "a/b", "x", "UPPER", "-lead"])
def test_skill_names_must_be_slugs(name):
    with pytest.raises(PathError):
        resolve_skill_path(name, "scripts/a.py")
