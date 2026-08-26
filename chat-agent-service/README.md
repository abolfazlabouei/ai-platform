# chat-agent-service

LangGraph-based chat & agent runtime. Implements everything described in
`../ARCHITECTURE.md` section 2.

## Run locally (Docker)

```bash
cd ai-platform
cp chat-agent-service/.env.example chat-agent-service/.env
# edit .env: set ANTHROPIC_API_KEY (or OPENAI_API_KEY)
docker compose up chat-agent-service postgres redis minio
```

Open http://localhost:8001/docs for interactive API docs (Swagger UI).

## Run locally (without Docker)

```bash
cd ai-platform
pip install -e shared-schemas
cd chat-agent-service
pip install -r requirements.txt
cp .env.example .env   # point DATABASE_URL/REDIS_URL at localhost services
uvicorn app.main:app --reload
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/chat/stream` | Ad-hoc chat, SSE stream. Body: `content_blocks`, optional `mcp_server_ids`, `knowledge_base_ids`, `conversation_id`. |
| POST | `/api/v1/chat/complete` | Same as above, non-streaming, returns final message. |
| POST | `/api/v1/agents` | Create an Agent (prompt, model, mcp servers, knowledge bases, tool policy). |
| GET | `/api/v1/agents` | List your agents, or `?is_composable=true` for the sub-agent registry. |
| GET/PATCH/DELETE | `/api/v1/agents/{id}` | Agent CRUD. |
| POST | `/api/v1/agents/{id}/chat/stream` | Chat with a specific agent, SSE stream. |
| POST | `/api/v1/agents/{id}/chat/complete` | Same, non-streaming. |
| GET | `/api/v1/conversations` | List your conversations. |
| GET | `/api/v1/conversations/{id}/messages` | Full history for a conversation. |
| DELETE | `/api/v1/conversations/{id}` | Delete a conversation. |
| POST | `/api/v1/conversations/{id}/tool-approval` | Resume a graph paused by a HITL-gated tool call. Body: `{"decisions": {"<tool_call_id>": true}}`. |
| POST | `/api/v1/mcp-servers` | Register an MCP server. |
| GET/DELETE | `/api/v1/mcp-servers` / `/{id}` | List/delete MCP servers. |
| POST | `/api/v1/mcp-servers/{id}/test-connection` | Connect + discover tools (cached as `pending`). |
| GET | `/api/v1/mcp-servers/{id}/tools` | List discovered tools for a server. |
| PATCH | `/api/v1/mcp-servers/{id}/tools/{tool_id}` | Approve/reject a tool, set `requires_hitl`. |
| GET | `/api/v1/knowledge-bases` | Proxy list of knowledge bases (from knowledge-service). |
| POST | `/api/v1/media/upload` | Proxy upload of an image/audio attachment (to file-processing-service). |
| GET | `/api/v1/media/{id}` | Resolve a media_id to a URL. |
| POST | `/api/v1/channel-identities/resolve` | Used by future gateways to map an external platform identity to an internal user + conversation. |

## SSE event types (`/chat/stream`, `/agents/{id}/chat/stream`)

`token` · `tool_call` · `tool_result` · `tool_approval_required` · `error` · `done`

## Typical HITL flow

1. Register a server: `POST /mcp-servers`
2. `POST /mcp-servers/{id}/test-connection` → returns discovered tools (all `pending`)
3. `PATCH /mcp-servers/{id}/tools/{tool_id}` with `{"approval_status": "approved", "requires_hitl": true}`
4. Chat normally. When the model calls that tool, the stream emits `tool_approval_required`
   instead of executing it.
5. `POST /conversations/{id}/tool-approval` with `{"decisions": {"<tool_call_id>": true}}`
   to resume — the graph continues from its checkpoint.

## Not yet included (see ARCHITECTURE.md for why)

- Alembic revisions are not pre-generated — run `alembic revision --autogenerate -m "init"` once
  a Postgres instance is reachable, then `alembic upgrade head`.
- Encryption at rest for `McpServer.auth_config` (currently plain JSON — add a KMS/Fernet layer
  before production use).
- Rate limiting / per-user concurrency caps on `/chat/stream` (Redis is wired in but the actual
  limiter middleware is left as a follow-up).

## Inter-service auth note

`/api/v1/knowledge-bases` (proxy) and `/api/v1/media/upload` forward the caller's
own bearer token on to knowledge-service / file-processing-service rather than
passing a bare `user_id`, since all three services validate JWTs against the same
shared `JWT_SECRET`. This keeps each service independently authoritative over
"who is this request really from" instead of trusting an unauthenticated claim
from a sibling service.
