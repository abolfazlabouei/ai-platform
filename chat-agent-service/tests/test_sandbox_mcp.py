"""
code-sandbox-service MCP integration: header minting, and that sandbox tools are
cached per conversation so one conversation can never call another's sandbox.
"""
import time
from types import SimpleNamespace

import jwt
import pytest

from app.core.config import settings
from app.mcp_manager import client_pool as cp
from app.mcp_manager.client_pool import McpClientPool, mint_sandbox_context


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_SHARED_SECRET", "k" * 32)
    monkeypatch.setattr(settings, "SANDBOX_CONTEXT_SECRET", "s" * 32)
    pool = McpClientPool()
    pool._sandbox_clients.clear()
    pool._tool_cache.clear()
    yield
    pool._sandbox_clients.clear()
    pool._tool_cache.clear()


def sandbox_server(**auth):
    return SimpleNamespace(id="srv-1", name="sandbox", user_id="owner", url="http://code-sandbox-service:8000/mcp",
                           transport=SimpleNamespace(value="streamable_http"),
                           auth_config={"type": "sandbox", **auth})


def test_context_jwt_claims_and_lifetime():
    token = mint_sandbox_context("conv-1", "user-1", now=1_000_000)
    claims = jwt.decode(token, "s" * 32, algorithms=["HS256"], options={"verify_exp": False})
    assert (claims["conversation_id"], claims["user_id"]) == ("conv-1", "user-1")
    assert claims["exp"] - claims["iat"] <= 300  # code-sandbox-service rejects anything longer


def test_connection_config_sets_sandbox_headers():
    cfg = McpClientPool()._connection_config(sandbox_server(), conversation_id="conv-1", user_id="user-1")
    assert cfg["transport"] == "streamable_http"
    assert cfg["headers"]["X-Sandbox-Key"] == "k" * 32
    claims = jwt.decode(cfg["headers"]["X-Sandbox-Context"], "s" * 32, algorithms=["HS256"])
    assert claims["conversation_id"] == "conv-1" and claims["user_id"] == "user-1"


def test_connection_config_non_sandbox_has_no_sandbox_headers():
    server = SimpleNamespace(id="x", name="n", user_id="u", url="http://x", transport=SimpleNamespace(value="sse"),
                             auth_config={"type": "bearer", "token": "t"})
    assert McpClientPool()._connection_config(server)["headers"] == {"Authorization": "Bearer t"}


class FakeClient:
    """Stands in for MultiServerMCPClient; records the headers each instance was built with."""
    built: list[dict] = []

    def __init__(self, connections):
        (self.cfg,) = connections.values()
        FakeClient.built.append(self.cfg)

    async def get_tools(self):
        conv = jwt.decode(self.cfg["headers"]["X-Sandbox-Context"], "s" * 32, algorithms=["HS256"])["conversation_id"]

        class Tool:
            name = "run_python"

            async def ainvoke(self, args, config=None):
                return f"ran in {conv}"

        return [Tool()]


async def test_sandbox_tools_are_isolated_per_conversation(monkeypatch):
    monkeypatch.setattr(cp, "MultiServerMCPClient", FakeClient)
    FakeClient.built.clear()
    pool, server = McpClientPool(), sandbox_server()

    await pool.as_langchain_tools([server], {"run_python"}, conversation_id="conv-A", user_id="u1")
    await pool.as_langchain_tools([server], {"run_python"}, conversation_id="conv-B", user_id="u2")

    assert await pool.call_tool("run_python", {}, conversation_id="conv-A", user_id="u1") == "ran in conv-A"
    assert await pool.call_tool("run_python", {}, conversation_id="conv-B", user_id="u2") == "ran in conv-B"
    assert len(FakeClient.built) == 2  # cached: no reconnect per call


async def test_no_identity_means_no_sandbox_tools(monkeypatch):
    monkeypatch.setattr(cp, "MultiServerMCPClient", FakeClient)
    tools = await McpClientPool().as_langchain_tools([sandbox_server()], {"run_python"})
    assert tools == []


async def test_call_for_unknown_conversation_cannot_reach_another_sandbox(monkeypatch):
    monkeypatch.setattr(cp, "MultiServerMCPClient", FakeClient)
    pool = McpClientPool()
    await pool.as_langchain_tools([sandbox_server()], {"run_python"}, conversation_id="conv-A", user_id="u1")
    with pytest.raises(ValueError):
        await pool.call_tool("run_python", {}, conversation_id="conv-B", user_id="u2")


async def test_aged_client_is_rebuilt_with_fresh_token(monkeypatch):
    monkeypatch.setattr(cp, "MultiServerMCPClient", FakeClient)
    FakeClient.built.clear()
    pool, server = McpClientPool(), sandbox_server()
    await pool.as_langchain_tools([server], {"run_python"}, conversation_id="conv-A", user_id="u1")
    tools, built_at, srv = pool._sandbox_clients[("srv-1", "conv-A")]
    pool._sandbox_clients[("srv-1", "conv-A")] = (tools, built_at - cp.SANDBOX_CLIENT_TTL_SECONDS - 1, srv)

    assert await pool.call_tool("run_python", {}, conversation_id="conv-A", user_id="u1") == "ran in conv-A"
    assert len(FakeClient.built) == 2  # rebuilt before the old JWT could expire
