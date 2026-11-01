"""Phase 2: skill_run_script -> code-sandbox-service (fake sandbox; the real one is covered by the manual e2e)."""
import base64
import json
import subprocess
import sys

import httpx
import pytest

from app.core.config import settings
from app.services.sandbox_client import SandboxClient, SandboxError
from app.services.skill_service import SkillService
from app.skills import package as pkg
from app.skills import tools as skill_tools
from app.skills.scripts import build_runner_code, format_result, run_skill_script_tool
from tests.skill_helpers import skill_md

USER = "user-1"


# ---------------- runner code ----------------

HOSTILE_ARGS = [
    "plain", "with space", "it's", 'say "hi"', "multi\nline", "'''", '"""', "\\", "$(rm -rf /)", "; echo pwned",
    "{{7*7}}", "کلینیک", "a\x00b" if False else "tab\there",
]


def test_runner_code_passes_arguments_verbatim_and_runs_as_main(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text("import sys, json\nprint(json.dumps({'name': __name__, 'argv': sys.argv}))\n")
    code = build_runner_code(str(script), HOSTILE_ARGS)
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    result = json.loads(out.stdout)
    assert result["name"] == "__main__"
    assert result["argv"] == [str(script), *HOSTILE_ARGS]


def test_arguments_are_data_not_code(tmp_path):
    marker = tmp_path / "pwned"
    script = tmp_path / "noop.py"
    script.write_text("pass\n")
    evil = [f"'); open({str(marker)!r}, 'w').write('x') #", f'"""; open({str(marker)!r}, "w").write("x") #']
    subprocess.run([sys.executable, "-I", "-c", build_runner_code(str(script), evil)], check=True)
    assert not marker.exists()


def test_format_result():
    text = format_result({"exit_code": 0, "duration_ms": 1500, "stdout": "ok\n", "stderr": "", "truncated": False,
                          "artifacts": [{"name": "c.png", "kind": "image", "url": "http://x/c.png"},
                                        {"name": "big.bin", "kind": "file", "error": "too large"}]})
    assert text.splitlines()[0] == "exit_code: 0 (1.5s)"
    assert "c.png (image): http://x/c.png" in text and "big.bin: too large" in text
    assert "TIMED OUT" in format_result({"exit_code": None, "duration_ms": 100, "timed_out": True, "stdout": "", "stderr": ""})


# ---------------- sandbox client ----------------


def mock_client(handler):
    return SandboxClient(transport=httpx.MockTransport(handler))


async def test_client_sends_key_and_json(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_SHARED_SECRET", "k" * 32)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers["x-sandbox-key"], json.loads(request.content)))
        return httpx.Response(200, json={"id": "sess-1"})

    client = mock_client(handler)
    assert await client.get_or_create_session("conv-1", "user-1") == "sess-1"
    assert seen == [("POST", "/api/v1/sessions", "k" * 32,
                     {"conversation_id": "conv-1", "user_id": "user-1", "language": "python"})]


@pytest.mark.parametrize("status, body, expect", [
    (429, {"detail": "you already have 3 active sandboxes"}, "3 active sandboxes"),
    (400, {"detail": "bad path"}, "bad path"),
    (401, {"detail": "Invalid or missing X-Sandbox-Key"}, "SANDBOX_SHARED_SECRET"),
])
async def test_client_maps_errors(status, body, expect):
    client = mock_client(lambda request: httpx.Response(status, json=body))
    with pytest.raises(SandboxError, match=expect):
        await client.execute("s", "print(1)", 5)


async def test_client_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(SandboxError, match="unreachable"):
        await mock_client(handler).execute("s", "print(1)", 5)


# ---------------- the tool ----------------


class FakeSandbox:
    def __init__(self, result=None, fail_at=None):
        self.calls, self.result, self.fail_at = [], result, fail_at

    def _step(self, name, *args):
        self.calls.append((name, *args))
        if self.fail_at == name:
            raise SandboxError(f"{name} failed")

    async def get_or_create_session(self, conversation_id, user_id):
        self._step("session", conversation_id, user_id)
        return "sess-1"

    async def import_skill(self, session_id, name, files):
        self._step("import_skill", session_id, name, sorted(p for p, _ in files), dict(files))

    async def import_document(self, session_id, file_id):
        self._step("import_document", session_id, file_id)

    async def execute(self, session_id, code, timeout):
        self._step("execute", session_id, code, timeout)
        return self.result or {"exit_code": 0, "duration_ms": 200, "stdout": "done\n", "stderr": "", "artifacts": []}


@pytest.fixture
async def scripted(db, session_maker, storage, monkeypatch):
    monkeypatch.setattr(skill_tools, "AsyncSessionLocal", session_maker)
    import app.skills.scripts as scripts_module

    monkeypatch.setattr(scripts_module, "AsyncSessionLocal", session_maker)
    service = SkillService(db, storage)
    package = pkg.parse_json(
        skill_md(name="price-analysis", body="# Analyze\nRun scripts/summarize.py.\n"),
        {"scripts/summarize.py": "print('hi')", "scripts/helper.py": "x = 1", "references/format.md": "# F",
         "scripts/run.sh": "echo no"},
    )
    created = await service.save_package(USER, package, update=False)
    skills = await service.resolve_for_runtime(USER, [{"skill_id": str(created.skill.id), "version": None}])
    runtime = {"user_id": USER, "conversation_id": "conv-9", "agent_id": None, "skills": skills}
    return runtime, {s["name"]: s for s in skills}, created


async def test_runs_script_in_sandbox_with_the_right_calls(scripted, storage):
    runtime, by_name, _ = scripted
    sandbox = FakeSandbox()
    tool = run_skill_script_tool(runtime, by_name, storage, client=sandbox)
    out = await tool.ainvoke({"name": "price-analysis", "script": "scripts/summarize.py", "args": ["--month", "ordibehesht"],
                              "input_file_ids": ["file-1"]})

    names = [c[0] for c in sandbox.calls]
    assert names == ["session", "import_skill", "import_document", "execute"]
    assert sandbox.calls[0][1:] == ("conv-9", USER)
    _, _, skill_name, paths, contents = sandbox.calls[1]
    assert skill_name == "price-analysis"
    assert paths == ["references/format.md", "scripts/helper.py", "scripts/run.sh", "scripts/summarize.py"]  # no SKILL.md
    assert contents["scripts/summarize.py"] == b"print('hi')"
    assert sandbox.calls[2][2] == "file-1"
    _, _, code, timeout = sandbox.calls[3]
    assert "/workspace/skills/price-analysis/scripts/summarize.py" in code and "ordibehesht" in code and timeout == 60
    assert out.splitlines()[0] == "exit_code: 0 (0.2s)" and "done" in out


@pytest.mark.parametrize("script", ["scripts/../../etc/passwd.py", "../x.py", "/etc/passwd", "references/format.md",
                                    "scripts/run.sh", "scripts/missing.py", "SKILL.md"])
async def test_only_stored_python_scripts_run(scripted, storage, script):
    runtime, by_name, _ = scripted
    sandbox = FakeSandbox()
    out = await run_skill_script_tool(runtime, by_name, storage, client=sandbox).ainvoke({"name": "price-analysis", "script": script})
    assert out.startswith("Error:") and "scripts/summarize.py" in out
    assert sandbox.calls == []  # nothing reached the sandbox


async def test_unknown_skill_and_arg_limits(scripted, storage):
    runtime, by_name, _ = scripted
    tool = run_skill_script_tool(runtime, by_name, storage, client=FakeSandbox())
    assert (await tool.ainvoke({"name": "nope", "script": "scripts/summarize.py"})).startswith("Error: unknown skill")
    too_many = await tool.ainvoke({"name": "price-analysis", "script": "scripts/summarize.py", "args": ["x"] * 33})
    assert too_many.startswith("Error: at most")


async def test_sandbox_failures_become_error_text(scripted, storage):
    runtime, by_name, _ = scripted
    for step in ("session", "import_skill", "import_document", "execute"):
        out = await run_skill_script_tool(runtime, by_name, storage, client=FakeSandbox(fail_at=step)).ainvoke(
            {"name": "price-analysis", "script": "scripts/summarize.py", "input_file_ids": ["f"]}
        )
        assert out == f"Error: {step} failed"


async def test_run_is_audited(scripted, storage, db):
    from sqlalchemy import select

    from app.models.skill import SkillUsage

    runtime, by_name, _ = scripted
    await run_skill_script_tool(runtime, by_name, storage, client=FakeSandbox()).ainvoke(
        {"name": "price-analysis", "script": "scripts/summarize.py"}
    )
    rows = (await db.execute(select(SkillUsage))).scalars().all()
    assert [(r.action, r.detail, r.conversation_id) for r in rows] == [("run", "scripts/summarize.py", "conv-9")]


# ---------------- wiring ----------------


async def test_script_tool_only_when_enabled_and_skill_has_scripts(scripted, storage, monkeypatch):
    runtime, _, _ = scripted
    assert "skill_run_script" not in skill_tools.build_skill_tools(runtime, storage)  # flag off (default)
    monkeypatch.setattr(settings, "SKILLS_SCRIPTS_ENABLED", True)
    assert "skill_run_script" in skill_tools.build_skill_tools(runtime, storage)
    no_scripts = {**runtime, "skills": [{**runtime["skills"][0], "has_scripts": False}]}
    assert "skill_run_script" not in skill_tools.build_skill_tools(no_scripts, storage)


async def test_skill_load_points_at_scripts_only_when_runnable(scripted, storage, monkeypatch):
    runtime, _, _ = scripted
    off = await skill_tools.build_skill_tools(runtime, storage)["skill_load"].ainvoke({"name": "price-analysis"})
    assert "skill_run_script" not in off
    monkeypatch.setattr(settings, "SKILLS_SCRIPTS_ENABLED", True)
    on = await skill_tools.build_skill_tools(runtime, storage)["skill_load"].ainvoke({"name": "price-analysis"})
    assert "Scripts (scripts/*.py) are run with skill_run_script" in on


async def test_script_runs_require_human_approval_by_default(scripted, session_maker, storage, monkeypatch):
    import uuid

    import app.services.chat_service as chat_service
    from app.services.chat_service import ChatService

    runtime, _, created = scripted

    async def no_tools(db, ids):
        return []

    monkeypatch.setattr(chat_service, "get_approved_tools", no_tools)
    async with session_maker() as db:
        rt = await ChatService(db)._build_runtime_config(
            uuid.uuid4(), USER, None, [], [], None, None, None, [{"skill_id": str(created.skill.id)}]
        )
    assert rt["tool_hitl_map"]["skill_run_script"] is True
