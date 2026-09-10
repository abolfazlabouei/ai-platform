# Gradio test GUI

A browser UI for exercising `chat-agent-service`, `file-processing-service`, and
`knowledge-service` without curl/Postman. See `../API.md` for the full API
reference this GUI is built against.

## Run standalone (against services running via docker-compose)

```bash
cd ..
docker compose up -d postgres redis minio qdrant chat-agent-service file-processing-service knowledge-service

cd gradio-gui
pip install -r requirements.txt
python app.py
```

Open http://localhost:7860. In the **Auth** tab, click "Generate dev token"
(uses the same shared dev JWT secret as `infra/scripts/generate_dev_token.py`)
or paste a token issued elsewhere.

Default base URLs point at the docker-compose host-port mapping
(`localhost:8101/8102/8103`). Override with env vars if needed:

```bash
export CHAT_BASE_URL=http://localhost:8001/api/v1   # if running chat-agent-service outside compose
export FILES_BASE_URL=http://localhost:8002/api/v1
export KB_BASE_URL=http://localhost:8003/api/v1
```

## Run via docker-compose

```bash
cd ..
docker compose up -d gradio-gui
```

This uses the internal container hostnames (`http://chat-agent-service:8000/api/v1`, etc.)
configured in `docker-compose.yml`.

## Tabs

- **Auth** — generate/paste a bearer token, shared across all other tabs.
- **Chat (ad-hoc)** — `/chat/complete` and `/chat/stream`, including the
  `clinic_id` field for testing the doctor-laser clinic-context injection.
- **Agents** — CRUD for reusable Agents, plus chat with a selected agent.
- **Conversations** — list/view/delete conversation history.
- **Tool Approval** — resume a paused human-in-the-loop tool-call stream.
- **MCP Servers** — register servers, discover/approve tools, test connections.
- **Media** — upload a chat attachment, resolve `media_id` to a URL.
- **Files (file-processing-service)** — upload documents, watch extraction/
  chunking job progress, inspect chunks.
- **Knowledge Bases (knowledge-service)** — CRUD, ingest files, run searches.
