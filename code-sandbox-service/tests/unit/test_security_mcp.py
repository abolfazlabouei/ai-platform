"""
Auth for the MCP interface: shared key + signed context, and that tool calls are
bound to the JWT's conversation — never to ids passed as arguments.
Runs the real MCP streamable-http app in-process; DB and Docker are faked.
"""
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import jwt
import pytest

from app.core.config import settings
from app.core.security import InvalidContext, context_from_headers, decode_context
from app.mcp_server import server as mcp_module

KEY = settings.SANDBOX_SHARED_SECRET


def make_token(conversation_id="conv-A", user_id="user-1", lifetime=60, secret=None, **extra):
    now = int(time.time())
    claims = {"conversation_id": conversation_id, "user_id": user_id, "iat": now, "exp": now + lifetime, **extra}
    return jwt.encode(claims, secret or settings.SANDBOX_CONTEXT_SECRET, algorithm="HS256")


# --- pure header validation ---


def test_valid_context():
    ctx = context_from_headers({"X-Sandbox-Key": KEY, "X-Sandbox-Context": make_token()})
    assert (ctx.conversation_id, ctx.user_id) == ("conv-A", "user-1")


@pytest.mark.parametrize("case", ["none", "empty", "no_key", "wrong_key", "no_context", "garbage_context"])
def test_missing_or_bad_headers(case):
    valid = make_token()
    headers = {
        "none": None,
        "empty": {},
        "no_key": {"X-Sandbox-Context": valid},
        "wrong_key": {"X-Sandbox-Key": "wrong", "X-Sandbox-Context": valid},
        "no_context": {"X-Sandbox-Key": KEY},
        "garbage_context": {"X-Sandbox-Key": KEY, "X-Sandbox-Context": "not-a-jwt"},
    }[case]
    with pytest.raises(InvalidContext):
        context_from_headers(headers)


def test_expired_context():
    with pytest.raises(InvalidContext):
        decode_context(make_token(lifetime=-10))


def test_wrong_signature():
    with pytest.raises(InvalidContext):
        decode_context(make_token(secret="not-the-secret"))


def test_overlong_lifetime_rejected():
    with pytest.raises(InvalidContext):
        decode_context(make_token(lifetime=3600))


def test_missing_claims_rejected():
    now = int(time.time())
    token = jwt.encode({"user_id": "u", "iat": now, "exp": now + 60}, settings.SANDBOX_CONTEXT_SECRET, "HS256")
    with pytest.raises(InvalidContext):
        decode_context(token)


# --- MCP over HTTP ---


class FakeSessions:
    def __init__(self):
        self.requested: list[tuple[str, str]] = []

    async def get_or_create(self, conversation_id, user_id, language):
        self.requested.append((conversation_id, user_id))
        return SimpleNamespace(id="sess", conversation_id=conversation_id, user_id=user_id)


@pytest.fixture
def fake_services(monkeypatch):
    sessions = FakeSessions()

    class FakeExecutions:
        async def run(self, row, code, timeout_seconds):
            return {"exit_code": 0, "duration_ms": 1200, "stdout": f"ran for {row.conversation_id}\n",
                    "stderr": "", "truncated": False, "timed_out": False, "oom_killed": False,
                    "workspace_reset": False, "sandbox_restarted": False,
                    "artifacts": [{"name": "chart.png", "kind": "image", "url": "http://s3/chart.png"}]}

    @asynccontextmanager
    async def fake_db():
        yield None

    monkeypatch.setattr(mcp_module, "AsyncSessionLocal", fake_db)
    monkeypatch.setattr(mcp_module, "build_services",
                        lambda db: SimpleNamespace(sessions=sessions, executions=FakeExecutions()))
    return sessions


@asynccontextmanager
async def mcp_client():
    # Not a fixture: the session manager's task group must enter and exit in the same task.
    app = mcp_module.build_mcp_app()
    async with mcp_module.mcp_lifespan():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sandbox") as c:
            yield c


def rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _call(client, headers, name, arguments):
    init = await client.post("/mcp", headers=headers, json=rpc("initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}))
    if init.status_code != 200:
        return init
    return await client.post("/mcp", headers=headers, json=rpc("tools/call", {"name": name, "arguments": arguments}, 2))


async def test_mcp_requires_shared_key(fake_services):
    async with mcp_client() as client:
        resp = await client.post("/mcp", headers=HEADERS, json=rpc("tools/list"))
        assert resp.status_code == 401
        assert fake_services.requested == []


async def test_tools_listed_with_key(fake_services):
    async with mcp_client() as client:
        headers = {**HEADERS, "X-Sandbox-Key": KEY}
        await client.post("/mcp", headers=headers, json=rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}))
        resp = await client.post("/mcp", headers=headers, json=rpc("tools/list", id_=2))
        assert resp.status_code == 200, resp.text
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert names == {"run_python", "import_document", "list_files", "read_file", "write_file", "reset_sandbox"}
        for tool in resp.json()["result"]["tools"]:
            props = set(tool["inputSchema"].get("properties", {}))
            assert not props & {"user_id", "conversation_id", "session_id"}


async def test_tool_call_without_context_is_tool_error(fake_services):
    async with mcp_client() as client:
        resp = await _call(client, {**HEADERS, "X-Sandbox-Key": KEY}, "run_python", {"code": "print(1)"})
        result = resp.json()["result"]
        assert result["isError"] is True
        assert "sandbox access denied" in result["content"][0]["text"]
        assert fake_services.requested == []


async def test_tool_call_with_expired_context_is_tool_error(fake_services):
    async with mcp_client() as client:
        headers = {**HEADERS, "X-Sandbox-Key": KEY, "X-Sandbox-Context": make_token(lifetime=-5)}
        result = (await _call(client, headers, "run_python", {"code": "print(1)"})).json()["result"]
        assert result["isError"] is True
        assert fake_services.requested == []


async def test_tool_call_bound_to_jwt_identity_not_arguments(fake_services):
    async with mcp_client() as client:
        headers = {**HEADERS, "X-Sandbox-Key": KEY, "X-Sandbox-Context": make_token("conv-A", "user-1")}
        resp = await _call(client, headers, "run_python",
                           {"code": "print(1)", "conversation_id": "conv-B", "user_id": "victim"})
        result = resp.json()["result"]
        assert result.get("isError") is not True, result
        text = result["content"][0]["text"]
        assert "ran for conv-A" in text
        assert "chart.png (image): http://s3/chart.png" in text
        assert fake_services.requested == [("conv-A", "user-1")]


def test_format_run_result_flags():
    text = mcp_module.format_run_result({
        "exit_code": None, "duration_ms": 5000, "stdout": "", "stderr": "killed", "truncated": True,
        "timed_out": True, "oom_killed": False, "workspace_reset": True, "sandbox_restarted": True,
        "artifacts": []})
    assert "TIMED OUT" in text
    assert "/workspace was empty again" in text
    assert "next call starts with an empty /workspace" in text
    assert "output truncated" in text
