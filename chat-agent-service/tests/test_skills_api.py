"""/skills and agent/chat skill references through the real FastAPI app (SQLite + in-memory store)."""
import io
import zipfile

import httpx
import pytest

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.main import app
from tests.skill_helpers import GOOD_MD, make_zip, skill_md


@pytest.fixture
async def api(session_maker, storage, monkeypatch):
    import app.services.skill_service as skill_service

    monkeypatch.setattr(skill_service, "get_storage", lambda: storage)

    async def override_db():
        async with session_maker() as session:
            yield session

    from fastapi import Header

    async def user_from_header(x_user: str = Header(default="user-1")):
        return CurrentUser(user_id=x_user, raw_claims={})

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_user] = user_from_header
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


def zip_upload(entries):
    return {"file": ("skill.zip", make_zip(entries), "application/zip")}


async def create(api, entries=None, user="user-1", update=False):
    entries = entries or {"SKILL.md": GOOD_MD, "references/format.md": "# Format"}
    return await api.post(f"/api/v1/skills?update={str(update).lower()}", files=zip_upload(entries), headers={"X-User": user})


# ---------------- upload / list / detail ----------------


async def test_upload_zip_then_list_and_detail(api):
    resp = await create(api)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1 and body["created_version"] is True and body["skill"]["name"] == "monthly-report"

    listing = (await api.get("/api/v1/skills")).json()
    assert [(s["name"], s["latest_version"], s["has_scripts"], s["used_by_agents"]) for s in listing] == [("monthly-report", 1, False, 0)]

    detail = (await api.get(f"/api/v1/skills/{body['skill']['id']}")).json()
    assert detail["latest"]["body"].startswith("# Monthly report")
    assert [f["path"] for f in detail["latest"]["files"]] == ["SKILL.md", "references/format.md"]
    assert [v["version"] for v in detail["versions"]] == [1]


async def test_upload_json_skill(api):
    resp = await api.post("/api/v1/skills", json={"skill_md": GOOD_MD, "files": {"references/a.md": "A"}})
    assert resp.status_code == 200 and resp.json()["skill"]["name"] == "monthly-report"


async def test_upload_single_skill_md_file(api):
    resp = await api.post("/api/v1/skills", files={"file": ("SKILL.md", GOOD_MD.encode(), "text/markdown")})
    assert resp.status_code == 200


async def test_invalid_upload_is_422_with_readable_errors(api):
    resp = await api.post("/api/v1/skills", files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert resp.status_code == 422
    assert resp.json()["errors"] == ["the upload is not a valid zip file"]
    assert "not a valid zip" in resp.json()["detail"]


async def test_zip_slip_upload_is_rejected(api):
    resp = await create(api, {"SKILL.md": GOOD_MD, "../evil.md": "x"})
    assert resp.status_code == 422


async def test_duplicate_name_is_409_until_update_true(api):
    assert (await create(api)).status_code == 200
    assert (await create(api, {"SKILL.md": skill_md(body="# changed\n")})).status_code == 409
    resp = await create(api, {"SKILL.md": skill_md(body="# changed\n")}, update=True)
    assert resp.status_code == 200 and resp.json()["version"] == 2


async def test_identical_reupload_returns_existing_version(api):
    first = (await create(api)).json()
    again = (await create(api, update=True)).json()
    assert again["version"] == first["version"] == 1 and again["created_version"] is False


async def test_validate_is_a_dry_run(api):
    ok = (await api.post("/api/v1/skills/validate", files=zip_upload({"SKILL.md": GOOD_MD, "scripts/a.py": "print(1)"}))).json()
    assert ok["valid"] is True and ok["name"] == "monthly-report" and ok["has_scripts"] is True
    bad = (await api.post("/api/v1/skills/validate", files=zip_upload({"references/a.md": "x"}))).json()
    assert bad["valid"] is False and "SKILL.md was not found" in bad["errors"][0]
    warn = (await api.post("/api/v1/skills/validate", json={"skill_md": skill_md(description="A generic helper for clinic staff members.")})).json()
    assert warn["valid"] and any("WHEN" in w for w in warn["warnings"])
    assert (await api.get("/api/v1/skills")).json() == []  # nothing was stored


# ---------------- files / edit / patch / download / delete ----------------


async def test_file_endpoint_text_and_binary(api):
    entries = {"SKILL.md": GOOD_MD, "references/format.md": "# Format", "assets/logo.png": b"\x89PNG\r\n\x1a\n"}
    sid = (await create(api, entries)).json()["skill"]["id"]
    text = (await api.get(f"/api/v1/skills/{sid}/versions/1/files", params={"path": "references/format.md"})).json()
    assert text["is_text"] and text["content"] == "# Format"
    binary = (await api.get(f"/api/v1/skills/{sid}/versions/1/files", params={"path": "assets/logo.png"})).json()
    assert not binary["is_text"] and binary["url"].startswith("http://files.test/")
    assert (await api.get(f"/api/v1/skills/{sid}/versions/1/files", params={"path": "../../etc/passwd"})).status_code == 404


async def test_edit_creates_a_new_version_keeping_other_files(api):
    sid = (await create(api)).json()["skill"]["id"]
    resp = await api.put(f"/api/v1/skills/{sid}", json={"skill_md": skill_md(body="# Edited\n"), "files": {"references/new.md": "N"}})
    assert resp.status_code == 200 and resp.json()["version"] == 2
    v2 = (await api.get(f"/api/v1/skills/{sid}/versions/2")).json()
    assert sorted(f["path"] for f in v2["files"]) == ["SKILL.md", "references/format.md", "references/new.md"]
    renamed = await api.put(f"/api/v1/skills/{sid}", json={"skill_md": skill_md(name="other-name")})
    assert renamed.status_code == 422


async def test_enable_disable(api):
    sid = (await create(api)).json()["skill"]["id"]
    resp = await api.patch(f"/api/v1/skills/{sid}", json={"is_enabled": False})
    assert resp.status_code == 200 and resp.json()["is_enabled"] is False


async def test_download_is_a_valid_zip_of_the_version(api):
    sid = (await create(api)).json()["skill"]["id"]
    resp = await api.get(f"/api/v1/skills/{sid}/download")
    assert resp.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(resp.content)).namelist()) == ["SKILL.md", "references/format.md"]


async def test_delete_removes_objects(api, storage):
    sid = (await create(api)).json()["skill"]["id"]
    assert storage.objects
    assert (await api.delete(f"/api/v1/skills/{sid}")).status_code == 204
    assert storage.objects == {} and (await api.get(f"/api/v1/skills/{sid}")).status_code == 404


async def test_other_users_cannot_see_or_touch_a_skill(api):
    sid = (await create(api, user="user-1")).json()["skill"]["id"]
    h = {"X-User": "user-2"}
    assert (await api.get("/api/v1/skills", headers=h)).json() == []
    assert (await api.get(f"/api/v1/skills/{sid}", headers=h)).status_code == 404
    assert (await api.patch(f"/api/v1/skills/{sid}", json={"is_enabled": False}, headers=h)).status_code == 404
    assert (await api.put(f"/api/v1/skills/{sid}", json={"skill_md": GOOD_MD}, headers=h)).status_code == 404
    assert (await api.get(f"/api/v1/skills/{sid}/download", headers=h)).status_code == 404
    assert (await api.delete(f"/api/v1/skills/{sid}", headers=h)).status_code == 404
    assert (await api.get(f"/api/v1/skills/{sid}/versions/1/files", params={"path": "SKILL.md"}, headers=h)).status_code == 404


# ---------------- agents ----------------


def agent_body(skill_ids=None, **extra):
    return {"name": "secretary", "system_prompt": "You help.", "skill_ids": skill_ids or [], **extra}


async def test_agent_gets_skills_and_lists_usage(api):
    sid = (await create(api)).json()["skill"]["id"]
    resp = await api.post("/api/v1/agents", json=agent_body([{"skill_id": sid, "version": None}]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["skill_ids"] == [{"skill_id": sid, "version": None}]
    assert (await api.get("/api/v1/skills")).json()[0]["used_by_agents"] == 1


async def test_agent_cannot_attach_another_users_skill(api):
    other = (await create(api, user="user-2")).json()["skill"]["id"]
    resp = await api.post("/api/v1/agents", json=agent_body([{"skill_id": other, "version": None}]))
    assert resp.status_code == 404


async def test_agent_pin_must_exist(api):
    sid = (await create(api)).json()["skill"]["id"]
    resp = await api.post("/api/v1/agents", json=agent_body([{"skill_id": sid, "version": 9}]))
    assert resp.status_code == 422 and "no version 9" in resp.json()["detail"]


async def test_agent_update_validates_and_null_means_unchanged(api):
    sid = (await create(api)).json()["skill"]["id"]
    other = (await create(api, {"SKILL.md": skill_md(name="other-skill")}, user="user-2")).json()["skill"]["id"]
    agent = (await api.post("/api/v1/agents", json=agent_body([{"skill_id": sid, "version": 1}]))).json()

    assert (await api.patch(f"/api/v1/agents/{agent['id']}", json={"skill_ids": [{"skill_id": other}]})).status_code == 404
    unchanged = await api.patch(f"/api/v1/agents/{agent['id']}", json={"skill_ids": None, "name": "renamed"})
    assert unchanged.status_code == 200 and unchanged.json()["skill_ids"] == [{"skill_id": sid, "version": 1}]
    cleared = await api.patch(f"/api/v1/agents/{agent['id']}", json={"skill_ids": []})
    assert cleared.json()["skill_ids"] == []


async def test_deleting_an_attached_skill_does_not_break_the_agent_or_runtime(api, session_maker, storage):
    from app.services.skill_service import SkillService

    sid = (await create(api)).json()["skill"]["id"]
    agent = (await api.post("/api/v1/agents", json=agent_body([{"skill_id": sid, "version": None}]))).json()
    await api.delete(f"/api/v1/skills/{sid}")

    assert (await api.get(f"/api/v1/agents/{agent['id']}")).status_code == 200  # agent API still works
    async with session_maker() as db:  # the chat turn simply runs without it
        assert await SkillService(db, storage).resolve_for_runtime("user-1", agent["skill_ids"]) == []


async def test_runtime_config_carries_skills_for_agents_and_adhoc(api, session_maker, storage, monkeypatch):
    from app.models.agent import Agent
    from app.services.chat_service import ChatService
    import app.services.skill_service as skill_service

    sid = (await create(api)).json()["skill"]["id"]
    agent_json = (await api.post("/api/v1/agents", json=agent_body([{"skill_id": sid, "version": None}]))).json()

    async def no_tools(db, ids):
        return []

    import app.services.chat_service as chat_service
    import uuid

    monkeypatch.setattr(chat_service, "get_approved_tools", no_tools)
    async with session_maker() as db:
        agent = await db.get(Agent, uuid.UUID(agent_json["id"]))
        service = ChatService(db)
        conv = uuid.uuid4()
        rt = await service._build_runtime_config(conv, "user-1", agent, [], [], None, None, None)
        assert [s["name"] for s in rt["skills"]] == ["monthly-report"]
        assert "- monthly-report:" in rt["skills_catalog"] and "skill_run_script" in rt["tool_hitl_map"]

        adhoc = await service._build_runtime_config(
            conv, "user-1", None, [], [], None, None, None, [{"skill_id": sid, "version": None}]
        )
        assert [s["name"] for s in adhoc["skills"]] == ["monthly-report"]

        none = await service._build_runtime_config(conv, "user-1", None, [], [], None, None, None)
        assert none["skills"] == [] and none["skills_catalog"] == "" and "skill_run_script" not in none["tool_hitl_map"]


async def test_adhoc_chat_rejects_foreign_skill(api):
    other = (await create(api, user="user-2")).json()["skill"]["id"]
    resp = await api.post("/api/v1/chat/complete", json={
        "content_blocks": [{"type": "text", "text": "hi"}], "skill_ids": [{"skill_id": other}],
    })
    assert resp.status_code == 404


async def test_rejected_adhoc_request_leaves_no_conversation_behind(api, session_maker):
    from sqlalchemy import func, select

    from app.models.conversation import Conversation

    other = (await create(api, user="user-2")).json()["skill"]["id"]
    await api.post("/api/v1/chat/stream", json={"content_blocks": [{"type": "text", "text": "hi"}], "skill_ids": [{"skill_id": other}]})
    async with session_maker() as db:
        assert (await db.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0
