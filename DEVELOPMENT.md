# Development Guide

This is the guide for engineers working *on* this repo (adding features, fixing
bugs, extending extractors/nodes/connectors). For consuming the API from a
frontend, see [`API.md`](./API.md). For local credentials, see
[`CREDENTIALS.md`](./CREDENTIALS.md). For the overall system design and why it's
shaped this way, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## 1. Prerequisites

- Python 3.11+
- Docker + Docker Compose (recommended path)
- An Anthropic and/or OpenAI API key (for `chat-agent-service`)
- An embedding provider API key (for `knowledge-service`, defaults to OpenAI)

## 2. Repository layout

```
ai-platform/
├── ARCHITECTURE.md          # system design rationale
├── DEVELOPMENT.md           # this file
├── API.md                   # frontend-facing API reference
├── CREDENTIALS.md           # all dev credentials in one place
├── docker-compose.yml       # all services + shared infra
├── infra/
│   ├── postgres-init/       # creates the 3 service databases on first boot
│   └── scripts/             # generate_dev_token.py, etc.
├── shared-schemas/          # pydantic contracts shared by all services
├── chat-agent-service/      # LangGraph chat/agent runtime
├── file-processing-service/ # upload, extract, chunk
├── knowledge-service/       # embed, vector search
├── gateways/                # [scaffold only] telegram/whatsapp/web adapters
└── multi-agent-orchestrator-service/  # [scaffold only]
```

Each service directory is internally consistent:

```
<service>/
├── app/
│   ├── main.py           # FastAPI entrypoint, router registration, lifespan
│   ├── core/              # config.py (settings), security.py (JWT), redis_client.py
│   ├── db/
│   │   ├── session.py     # async engine/session
│   │   └── migrations/    # Alembic (env.py, versions/)
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic request/response models
│   ├── repositories/       # CRUD-only DB access, no business logic
│   ├── services/           # business logic, orchestrates repos + external calls
│   ├── api/v1/              # FastAPI routers — thin, delegate to services/
│   └── workers/            # (file-processing/knowledge only) Celery app + tasks
├── tests/
├── requirements.txt
├── Dockerfile
├── entrypoint.sh            # runs `alembic upgrade head` then starts uvicorn
├── alembic.ini
└── .env.example
```

`chat-agent-service` additionally has `graphs/` (the LangGraph topology + nodes)
and `mcp_manager/` (MCP server connection pooling + tool registry).

## 3. Running everything locally

```bash
cd ai-platform
cp chat-agent-service/.env.example chat-agent-service/.env
cp file-processing-service/.env.example file-processing-service/.env
cp knowledge-service/.env.example knowledge-service/.env

# fill in the two required secrets (see CREDENTIALS.md):
#   chat-agent-service/.env   -> ANTHROPIC_API_KEY
#   knowledge-service/.env    -> EMBEDDING_API_KEY

docker compose up \
  postgres redis minio qdrant \
  chat-agent-service \
  file-processing-service file-processing-worker \
  knowledge-service knowledge-worker
```

Each API's Swagger UI is at `/docs`:
- chat-agent-service: http://localhost:8001/docs
- file-processing-service: http://localhost:8002/docs
- knowledge-service: http://localhost:8003/docs

Every request needs `Authorization: Bearer <token>` — generate one with
`infra/scripts/generate_dev_token.py` (see CREDENTIALS.md). Swagger UI's
"Authorize" button accepts it directly.

### Running a single service outside Docker

```bash
cd ai-platform
pip install -e shared-schemas
cd <service>
pip install -r requirements.txt
cp .env.example .env   # point DATABASE_URL/REDIS_URL/etc. at localhost
alembic upgrade head
uvicorn app.main:app --reload --port 800X
```

For file-processing-service / knowledge-service, also run the Celery worker in
a second terminal (commands are in each service's README).

## 4. Database migrations (Alembic)

Every service manages its schema via Alembic; `entrypoint.sh` runs
`alembic upgrade head` automatically on container start, so you normally never
run migrations by hand in Docker. When developing locally without Docker, or
after changing a model:

```bash
cd <service>
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/<db_name>
alembic revision --autogenerate -m "describe the change"
# review the generated file in app/db/migrations/versions/ before committing —
# autogenerate does NOT emit `DROP TYPE` for Postgres ENUMs when a table is
# dropped, so any migration that drops an enum-typed column/table needs a
# manual `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)` added to
# downgrade() (see the existing "init" migrations for the pattern)
alembic upgrade head
```

Test the roundtrip before committing:
```bash
alembic downgrade -1   # or `base` for a full wipe
alembic upgrade head
```

## 5. Testing

Each service has its own test suite (pure-logic smoke tests — no live
Postgres/Redis/Qdrant/LLM required):

```bash
cd <service>
pip install -r requirements.txt
pytest tests/ -v
```

- `chat-agent-service`: graph routing logic (`_route_after_llm`), HITL rejection
  bookkeeping.
- `file-processing-service`: extractors run against real in-memory generated
  files (docx via python-docx, pdf via PyMuPDF, xlsx via openpyxl, markdown via
  markdown-it-py) — not mocks. Chunkers are tested as pure functions.
- `knowledge-service`: collection-naming, embedding batching (provider mocked),
  cross-collection search merge/sort (Qdrant client mocked).

There is currently no integration test suite that spins up real Postgres/Redis/
Qdrant/MinIO — the fastest way to smoke-test the full stack end-to-end is
`docker compose up` + the flow in `API.md`'s "end-to-end example" section.

## 6. Common extension points

| I want to... | Where to look |
|---|---|
| Add a new document format to extract | `file-processing-service/app/workers/extractors/` — add `my_format_extractor.py` returning the same raw-block shape (`{"kind": "paragraph"\|"table"\|"image", ...}`), then register it in `tasks.py`'s `_EXTRACTORS` dict and `file_service.py`'s `_EXTENSION_TO_TYPE` map, plus a new `FileType` enum value + migration. |
| Add a new LLM provider | `chat-agent-service/app/graphs/llm_providers/__init__.py` — add a branch in `build_chat_model()`. |
| Add a new embedding provider | `knowledge-service/app/services/embedding_service.py` — add a branch in `_embed_batch_sync()`. |
| Change chunking strategy | `file-processing-service/app/workers/chunkers/` — `text_chunker.py`, `table_chunker.py`, `image_chunker.py` are independent, swappable functions. |
| Add a new graph node (e.g. reranking, moderation) | `chat-agent-service/app/graphs/nodes/` — write the node, wire it into `builder.py`'s `StateGraph` with a new edge/conditional edge. |
| Add a new channel gateway (Telegram, WhatsApp, ...) | `gateways/<name>/` (currently scaffolded only) — see `ARCHITECTURE.md` section 5 and the `ChannelIdentity` model already wired into `chat-agent-service`. |
| Add a new agent-callable capability | Any agent's `/agents/{id}/chat/complete` is already a stable external contract — a future `multi-agent-orchestrator-service` treats it as a sub-agent call via `is_composable=true` + `capabilities[]`. |

## 7. Code style / conventions

- Routers (`api/v1/*.py`) stay thin: parse request → call a `services/*.py`
  method → shape the response. No SQLAlchemy queries directly in routers.
- Repositories (`repositories/*.py`) are CRUD-only — no business rules, no
  cross-service HTTP calls.
- Services (`services/*.py`) hold business logic and are the only place that
  calls repositories, external HTTP clients, or (for chat-agent-service) the
  compiled LangGraph.
- Every module-level docstring explains *why*, not just *what* — when in doubt,
  read the top of the file before the function bodies.
- Sync vs async: FastAPI request handlers are async throughout; Celery tasks
  (file-processing-service, knowledge-service) run in a separate sync world
  with their own sync DB session (`app/workers/db.py`) and sync object-store/
  vector-store functions — don't mix `await` into task bodies.

## 8. Known gaps (see also each service's README "Not yet included")

- No ownership/authorization checks beyond "does a valid JWT exist" — e.g. any
  authenticated user can currently read/delete any file by id in
  file-processing-service. Add `row.user_id == current_user.user_id` checks
  before any multi-tenant production use.
- No encryption at rest for `McpServer.auth_config` (stored as plain JSON).
- No rate limiting on `/chat/stream` (Redis is wired in; the limiter itself is
  a follow-up).
- No virus/malware scanning on file upload.
- No OCR for scanned/image-only PDFs.
- `gateways/*` and `multi-agent-orchestrator-service` are scaffolds only.
