# Credentials (local development only)

**Every value on this page is a development default checked into `.env.example`
files and `docker-compose.yml`. None of them are safe to use anywhere except a
disposable local machine.** Before deploying to any shared, staging, or
production environment, regenerate all of the following and inject them via a
real secrets manager (not committed `.env` files).

---

## PostgreSQL

| | |
|---|---|
| Host (docker-compose) | `postgres` (service name) / `localhost` if run outside Docker |
| Port | `5432` |
| User | `postgres` |
| Password | `postgres` |
| Databases | `chat_agent_db`, `file_processing_db`, `knowledge_db` (auto-created by `infra/postgres-init/init-databases.sh` on first container start) |

Connection string pattern used by all three services:
```
postgresql+asyncpg://postgres:postgres@postgres:5432/<db_name>
```

## Redis

| | |
|---|---|
| Host | `redis` / `localhost` |
| Port | `6379` |
| Password | *(none — no auth configured for local dev)* |
| DB index | `1` = chat-agent-service, `2` = file-processing-service, `3` = knowledge-service (logical separation only, same Redis instance) |

## MinIO (S3-compatible object storage)

| | |
|---|---|
| Console URL | http://localhost:9001 |
| API endpoint | http://localhost:9000 (or `http://minio:9000` inside docker-compose) |
| Root user | `minioadmin` |
| Root password | `minioadmin` |
| Buckets (auto-created on first use by each service) | `raw-files`, `extracted-images` (file-processing-service), `generated-media` (chat-agent-service) |

## Qdrant (vector database)

| | |
|---|---|
| URL | http://localhost:6333 (or `http://qdrant:6333` inside docker-compose) |
| Auth | *(none — no API key configured for local dev)* |
| Collections | one per knowledge base, named `kb_<knowledge_base_id>`, auto-created on first ingest |

## JWT (shared across all three services)

All three services (`chat-agent-service`, `file-processing-service`,
`knowledge-service`) validate bearer tokens against **the same secret**, since
they're designed to trust a single upstream auth/gateway layer. In this
scaffold there is no real auth service — you generate dev tokens yourself.

| | |
|---|---|
| Secret | `dev-shared-jwt-secret-change-in-production` |
| Algorithm | `HS256` |
| Required claim | `sub` (or `user_id`) — becomes the internal `user_id` every row is scoped by |

### Generating a dev token

```bash
cd ai-platform/infra/scripts
python3 generate_dev_token.py demo-user-1
# prints a JWT valid for 24h, signed with the shared dev secret above
```

Use it in requests as:
```
Authorization: Bearer <token>
```

The same token works against all three services' Swagger UI (click "Authorize"
in `/docs` and paste `Bearer <token>`).

## Embedding provider (knowledge-service)

Not a checked-in credential — you must supply your own:

| Env var | Where |
|---|---|
| `EMBEDDING_API_KEY` | `knowledge-service/.env` |

Defaults to OpenAI's `text-embedding-3-small` (1536 dimensions). If you switch
provider/model, also update `EMBEDDING_DIMENSIONS` to match, since it's used
when creating each Qdrant collection.

## LLM provider (chat-agent-service)

Also not checked in:

| Env var | Where |
|---|---|
| `ANTHROPIC_API_KEY` | `chat-agent-service/.env` |
| `OPENAI_API_KEY` | `chat-agent-service/.env` (only if you use `model_provider: "openai"` on an agent/request) |

---

## Quick setup checklist

```bash
cd ai-platform
cp chat-agent-service/.env.example chat-agent-service/.env
cp file-processing-service/.env.example file-processing-service/.env
cp knowledge-service/.env.example knowledge-service/.env

# edit chat-agent-service/.env  -> set ANTHROPIC_API_KEY
# edit knowledge-service/.env   -> set EMBEDDING_API_KEY

docker compose up postgres redis minio qdrant \
  chat-agent-service \
  file-processing-service file-processing-worker \
  knowledge-service knowledge-worker
```

Every `.env` file already has matching, working defaults for Postgres/Redis/MinIO/
Qdrant/JWT — the only two values you must fill in yourself are the two API keys
above.
