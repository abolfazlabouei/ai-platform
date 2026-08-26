# knowledge-service

Knowledge base CRUD, ingest (pulls chunks from file-processing-service and embeds
them into a per-KB Qdrant collection), and vector search consumed directly by
chat-agent-service's `knowledge_retrieval` graph node. Implements everything in
`../ARCHITECTURE.md` section 4.

## Architecture within this service

```
FastAPI                                Celery worker (embed_kb_source)
   │                                            │
   ├─ POST /knowledge-bases                     │
   │  creates KnowledgeBase row                 │
   │  (Qdrant collection created lazily,         │
   │   on first ingest)                          │
   │                                            │
   ├─ POST /knowledge-bases/{id}/ingest          │
   │  {file_ids: [...]}                          │
   │  → creates/reuses a KBSource per file        │
   │  → enqueues embed_kb_source per file ───────┤ GET file-processing-service
   │                                             │  /files/{id}/chunks
   │                                             │
   │                                             ├ embeds each chunk's content
   │                                             │  (batched, via EMBEDDING_PROVIDER)
   │                                             │
   │                                             ├ upserts vectors into
   │                                             │  Qdrant collection kb_{kb_id}
   │                                             │  with payload {chunk_id, file_id,
   │                                             │  type, content, order_index}
   │                                             │
   ├─ GET /jobs/{id}/stream ◄────────────────────┤ publishes progress to
   │  (SSE, same pattern as                       │ Redis channel job:{id}
   │  file-processing-service)                    │
   │                                              │
   └─ POST /search {kb_ids, query, top_k}
      embeds the query, searches each kb's
      collection, merges + sorts by score
```

One Qdrant **collection per knowledge base** (`kb_{kb_id}`) — this keeps deletion
trivial (drop the collection) and avoids cross-tenant filtering inside a single
collection.

## Run locally (Docker)

```bash
cd ai-platform
cp knowledge-service/.env.example knowledge-service/.env
# set EMBEDDING_API_KEY in .env
docker compose up knowledge-service knowledge-worker postgres redis qdrant
```

Open http://localhost:8003/docs for interactive API docs.

## Run locally (without Docker)

```bash
cd ai-platform
pip install -e shared-schemas
cd knowledge-service
pip install -r requirements.txt
cp .env.example .env

# terminal 1 — API
uvicorn app.main:app --reload --port 8003

# terminal 2 — worker
celery -A app.workers.celery_app worker -Q embedding -l info --concurrency=4
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/knowledge-bases` | Create a knowledge base. |
| GET | `/api/v1/knowledge-bases` | List your knowledge bases. |
| GET/PATCH/DELETE | `/api/v1/knowledge-bases/{id}` | KB CRUD (delete also drops the Qdrant collection). |
| GET | `/api/v1/knowledge-bases/{id}/sources` | List files linked into this KB + their ingest status. |
| POST | `/api/v1/knowledge-bases/{id}/ingest` | `{"file_ids": [...]}` — enqueues one embed job per file. |
| POST | `/api/v1/search` | `{"kb_ids": [...], "query": "...", "top_k": 6}` — called by chat-agent-service. |
| GET | `/api/v1/jobs/{id}/status` | Current stage of an ingest job. |
| GET | `/api/v1/jobs/{id}/stream` | SSE stream of live embedding progress. |

## Embedding provider

Configured via `EMBEDDING_PROVIDER` (currently `openai`; add a new branch in
`app/services/embedding_service.py::_embed_batch_sync` to support another
provider — `EMBEDDING_DIMENSIONS` must match the chosen model's output size,
since it's used when creating the Qdrant collection).

## Not yet included

- Alembic revisions are not pre-generated — run `alembic revision --autogenerate -m "init"` once Postgres is reachable, then `alembic upgrade head`.
- Re-ingest / delta-update when a file's chunks change (currently `ingest_file` always creates fresh vectors on re-ingest; consider `delete_by_file_sync` + re-upsert as a "refresh" endpoint).
- Image-chunk-specific embedding path (currently image chunks are embedded via their caption text only — see `embed_tasks.py` docstring for where a vision-embedding branch would go).
