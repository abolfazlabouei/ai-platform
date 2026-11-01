# code-sandbox-service

Isolated code execution for agents. One long-lived gVisor sandbox container per conversation
(persistent `/workspace`), exposed to `chat-agent-service` as an **MCP server** (`/mcp`) so the
existing tool approval / HITL / tracing applies, plus a REST API (`/api/v1`) for tests and ops.

**Threat model:** the code is written by an LLM whose input can include untrusted text. Assume it is
hostile. Sandboxes have no network, no secrets, no host mounts, a read-only rootfs, and hard CPU /
memory / pid / time / output / disk limits (`app/sandbox/spec.py`, asserted by `tests/unit/test_spec.py`).

## Layout

| Path | Role |
|---|---|
| `app/sandbox/spec.py` | the security-critical `containers.create` kwargs |
| `app/sandbox/docker_backend.py` | **all** Docker SDK calls (one place to audit) |
| `app/sandbox/executor.py` | code delivered as a file, run with an argv list (no shell), host-side deadline |
| `app/sandbox/{warm_pool,reaper}.py` | pre-started containers; idle/expiry reaping + orphan cleanup |
| `app/services/` | session lifecycle, execution (lock, limits, audit), artifacts → MinIO, document import |
| `app/mcp_server/server.py` | MCP tools: `run_python`, `import_document`, `list_files`, `read_file`, `write_file`, `reset_sandbox` |
| `images/python/` | sandbox image (pinned analysis stack + Vazirmatn font) |

## Auth

Every request needs `X-Sandbox-Key` (shared secret). MCP tool calls additionally need
`X-Sandbox-Context`, a ≤5-minute HS256 JWT `{conversation_id, user_id}` minted by chat-agent-service.
Identity is taken **only** from that JWT — no tool accepts a user/conversation/session id argument.

## Setup

```bash
openssl rand -hex 32   # -> SANDBOX_SHARED_SECRET   (same value in chat-agent-service/.env)
openssl rand -hex 32   # -> SANDBOX_CONTEXT_SECRET  (same value in chat-agent-service/.env)
cp .env.example .env   # fill the two secrets
docker compose --profile build build sandbox-python-image
docker compose up -d code-sandbox-service
```

Register in chat-agent-service: `POST /api/v1/mcp-servers` with `transport: "streamable_http"`,
`url: "http://code-sandbox-service:8000/mcp"`, `auth_config: {"type": "sandbox"}`, then
`test-connection` and approve the tools.

## Tests

```bash
pip install -r requirements.txt fakeredis aiosqlite
pytest tests/unit                          # no Docker
SANDBOX_RUNTIME=runsc pytest -m integration tests/integration   # real Docker + runtime + image
```

On a laptop without gVisor use `SANDBOX_RUNTIME=runc`; everything runs except the gVisor kernel check.

## Known limits

- `SANDBOX_RUNTIME=runc` shares the host kernel — fine for development, **not** for hostile code.
- Docker socket = root on the host; keep this service off any published port.
- tmpfs workspaces are RAM: `SANDBOX_WORKSPACE_SIZE × SANDBOX_MAX_SESSIONS` must fit in host memory.
- No `pip install` at runtime (no network); the image's library list is the contract.
- Phase 4 (not built): egress allowlist, stateful kernels.
