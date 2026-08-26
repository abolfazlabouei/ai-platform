# AI Platform (Chat/Agent + File Processing + Knowledge Base)

Modular microservice backend. **All three core services are now implemented.**

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design and rationale
- [`DEVELOPMENT.md`](./DEVELOPMENT.md) — guide for engineers working on this repo
- [`API.md`](./API.md) — API reference for frontend integration
- [`CREDENTIALS.md`](./CREDENTIALS.md) — all local dev credentials in one place

## Services

- **chat-agent-service** — ✅ **implemented**. LangGraph-based chat & agent runtime:
  streaming (`/chat/stream`, SSE) + complete (`/chat/complete`) endpoints, full Agent
  CRUD with per-agent chat endpoints, MCP server registration + tool discovery +
  per-tool approve/reject with human-in-the-loop gating, knowledge-base retrieval,
  multimodal (text/image/audio) input and generated-image output, conversation
  history, and channel-identity groundwork for future gateways.
  See `chat-agent-service/README.md`.
- **file-processing-service** — ✅ **implemented**. Upload, extract (docx/pdf/xlsx/
  markdown — including tables and embedded images), and chunk documents. Runs
  extraction/chunking asynchronously via Celery, with live progress pushed over
  Redis pub/sub + SSE. Exposes `/files/{id}/chunks` for knowledge-service ingest.
  See `file-processing-service/README.md`.
- **knowledge-service** — ✅ **implemented**. Knowledge base CRUD, ingest (pulls
  chunks from file-processing-service, embeds them, upserts into a per-KB Qdrant
  collection via Celery), and `/search` — consumed directly by chat-agent-service's
  `knowledge_retrieval` graph node.
  See `knowledge-service/README.md`.

## Future (scaffolded only)
- gateways/telegram-gateway, gateways/whatsapp-gateway : channel adapters
- multi-agent-orchestrator-service                      : agent-to-agent orchestration

## Running everything locally

```bash
cp chat-agent-service/.env.example chat-agent-service/.env       # set ANTHROPIC_API_KEY
cp file-processing-service/.env.example file-processing-service/.env
cp knowledge-service/.env.example knowledge-service/.env         # set EMBEDDING_API_KEY

docker compose up \
  chat-agent-service \
  file-processing-service file-processing-worker \
  knowledge-service knowledge-worker \
  postgres redis minio qdrant
```

- chat-agent-service docs: http://localhost:8001/docs
- file-processing-service docs: http://localhost:8002/docs
- knowledge-service docs: http://localhost:8003/docs

## End-to-end flow

1. Upload a file: `POST file-processing-service:8002/api/v1/files`
2. Watch it get extracted+chunked: `GET .../api/v1/jobs/{job_id}/stream`
3. Create a knowledge base: `POST knowledge-service:8003/api/v1/knowledge-bases`
4. Ingest the file into it: `POST .../api/v1/knowledge-bases/{kb_id}/ingest {"file_ids": [...]}`
5. Chat with that knowledge base selected: `POST chat-agent-service:8001/api/v1/chat/complete`
   with `knowledge_base_ids: ["<kb_id>"]` — the `knowledge_retrieval` graph node calls
   knowledge-service's `/search` automatically.
