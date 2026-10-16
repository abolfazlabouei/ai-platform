# API Reference (for frontend integration)

Three services, three base URLs (local dev via docker-compose):

| Service | Base URL | Purpose |
|---|---|---|
| chat-agent-service | `http://localhost:8001/api/v1` | chat, agents, MCP, conversations |
| file-processing-service | `http://localhost:8002/api/v1` | file upload, extraction status, chunks |
| knowledge-service | `http://localhost:8003/api/v1` | knowledge base CRUD, ingest, search |

**In almost all cases the frontend only needs to talk to
`chat-agent-service`.** It proxies file upload (`/media/upload`) and knowledge
base listing (`/knowledge-bases`) internally. Talk to file-processing-service
and knowledge-service directly only for their richer management UIs (a file
manager screen, a knowledge-base admin screen, upload progress bars, etc.).

---

## Authentication

Every endpoint requires:
```
Authorization: Bearer <jwt>
```

All three services validate the token against the same shared secret (see
`CREDENTIALS.md`). For local dev, generate one with:
```bash
python3 infra/scripts/generate_dev_token.py <any-user-id>
```
In production this token is issued by whatever upstream auth/gateway layer you
put in front of these services — that piece is intentionally not part of this
repo.

## Content blocks — the multimodal message format

Every message (sent or received) is a list of typed blocks, not a plain
string. This is the single format used everywhere: chat requests, chat
responses, and conversation history.

```ts
type ContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; media_id?: string; url?: string; mime?: string }
  | { type: "audio"; media_id?: string; url?: string; mime?: string; duration_seconds?: number }
  | { type: "generated_image"; url: string; media_id?: string; mime: string; width?: number; height?: number; thumbnail_base64?: string; base64?: string }
  | { type: "tool_call"; tool_call_id: string; server_id: string; tool_name: string; arguments: object }
  | { type: "tool_result"; tool_call_id: string; tool_name: string; is_error: boolean; content: string | object }
```

**Sending an image/audio attachment:** upload it first, then reference it:
```
1. POST /media/upload  (multipart/form-data, field name "file")
   -> { "media_id": "uploads/<user>/<uuid>.png", "type": "image", "mime": "image/png", "url": "..." }
2. Use that media_id in an image/audio content block:
   { "type": "image", "media_id": "<media_id>" }
```
Images: png, jpeg, webp, gif. Audio: wav, mp3, ogg, flac, aac, m4a (browser
`audio/webm` recordings are not accepted; convert to wav/mp3 first). Max size:
`MAX_MEDIA_UPLOAD_MB` (20MB). Image blocks may instead carry a public http(s)
`url` (fetched by the model provider); either kind may carry a `data:` URL.
Only `text`, `image` and `audio` blocks are accepted as user input.

**Receiving a generated image:** when the user asks for an image, the model
calls the built-in `generate_image` tool (Nano Banana via OpenRouter, see
`IMAGE_GEN_MODEL`). The stream emits an `image` SSE event with the
`generated_image` block as soon as it is ready, and the block is saved on the
assistant message. Render `url` directly. To edit an uploaded or generated
image, just ask — the model passes its `media_id` to the tool as a reference.

---

## chat-agent-service

### Ad-hoc chat (no Agent — pick MCP servers / knowledge bases per request)

**`POST /chat/stream`** — Server-Sent Events

Request:
```json
{
  "conversation_id": null,
  "content_blocks": [{ "type": "text", "text": "What's in my uploaded contract?" }],
  "mcp_server_ids": [],
  "knowledge_base_ids": ["a1b2c3..."],
  "model_provider": null,
  "model_name": null
}
```
Omit `conversation_id` to start a new conversation; the first SSE-adjacent
response (see below) — or, simpler, the response to a parallel
`/conversations` list call — will show you the newly created id. In practice,
capture it from the `done` event's associated conversation, or use
`/chat/complete` for the very first turn if you need the id synchronously.

Response — a stream of SSE frames, each `event: <type>\ndata: <json>\n\n`:

| event | data shape | meaning |
|---|---|---|
| `token` | `{"text": "..."}` | incremental assistant text — append to the current message as it streams |
| `tool_call` | `{"tool_name": "...", "input": {...}}` | model invoked a tool (already approved, no action needed from the UI beyond an optional "using tool X..." indicator) |
| `tool_result` | `{"tool_name": "...", "output": "..."}` | that tool call finished |
| `tool_approval_required` | `{"type": "tool_approval_required", "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}]}` | **the graph is paused.** Show an approve/reject UI for each call, then call `/conversations/{id}/tool-approval` (see below) |
| `image` | `{"type": "generated_image", "media_id": "...", "url": "...", "mime": "image/png"}` | a generated image is ready — render `url` |
| `error` | `{"message": "..."}` | something failed; the stream ends after this |
| `done` | `{}` | turn complete |

Minimal frontend consumption (browser `EventSource` doesn't support POST, so
use `fetch` + a streaming reader, or a small SSE client library):
```js
const resp = await fetch(`${BASE}/chat/stream`, {
  method: "POST",
  headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({ conversation_id, content_blocks: [{ type: "text", text }] }),
});
const reader = resp.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  // split on "\n\n", parse each "event: X\ndata: Y" frame, dispatch by type
}
```

**`POST /chat/complete`** — same request body, non-streaming.

Response:
```json
{
  "conversation_id": "a1b2c3...",
  "content_blocks": [{ "type": "text", "text": "Your contract mentions..." }]
}
```
Use this for the very first message of a new conversation if you need the
`conversation_id` back synchronously (e.g. to update the URL/route), or
whenever you don't need token-by-token streaming.

### Agents

An Agent bundles a system prompt, model, MCP servers, knowledge bases, and a
tool-approval policy into something reusable and independently chattable.

**`POST /agents`**
```json
{
  "name": "Support Bot",
  "description": "Answers questions from the product knowledge base",
  "system_prompt": "You are a helpful support agent for Acme Corp...",
  "model_config": { "provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0.7 },
  "mcp_server_ids": [],
  "knowledge_base_ids": ["a1b2c3..."],
  "tool_policy": [],
  "capabilities": ["customer_support"],
  "is_composable": false
}
```
Returns the created `AgentOut` (same shape, plus `id`, `created_at`, `updated_at`).

**`GET /agents`** — list your agents.
**`GET /agents?is_composable=true`** — list agents flagged as callable sub-agents (for a future multi-agent orchestrator; irrelevant to a normal chat frontend).
**`GET /agents/{id}`** / **`PATCH /agents/{id}`** / **`DELETE /agents/{id}`** — standard CRUD.

**`POST /agents/{id}/chat/stream`** and **`POST /agents/{id}/chat/complete`** —
identical request/response/SSE shape to the ad-hoc endpoints above, except
`mcp_server_ids`/`knowledge_base_ids`/`model_provider`/`model_name` in the
request body are ignored (the Agent's own configuration is used instead). Only
`conversation_id` and `content_blocks` matter here.

### Conversations (history)

**`GET /conversations?limit=50&offset=0`**
```json
[
  { "id": "...", "agent_id": null, "mode": "ad_hoc", "channel": "api", "title": null, "created_at": "...", "updated_at": "..." }
]
```

**`GET /conversations/{id}/messages?limit=50`**
```json
[
  { "id": "...", "role": "user", "content_blocks": [{ "type": "text", "text": "..." }], "created_at": "..." },
  { "id": "...", "role": "assistant", "content_blocks": [{ "type": "text", "text": "..." }], "created_at": "..." }
]
```
Use this to hydrate a conversation when the user reopens it — it's the
durable record independent of the LangGraph checkpoint.

**`DELETE /conversations/{id}`** — deletes the conversation and its messages.

### Human-in-the-loop tool approval

When a stream emits `tool_approval_required`, render each `tool_calls[]` entry
(name + arguments) with approve/reject controls, then:

**`POST /conversations/{id}/tool-approval`**
```json
{ "decisions": { "<tool_call_id_1>": true, "<tool_call_id_2>": false } }
```
This call **also returns an SSE stream** (same event vocabulary as
`/chat/stream`) — the graph resumes from where it paused and continues
generating. Consume it exactly like `/chat/stream`'s response.

### MCP servers

**`POST /mcp-servers`**
```json
{ "name": "My Tools Server", "transport": "sse", "url": "https://example.com/mcp", "auth_config": { "type": "bearer", "token": "..." } }
```

**`POST /mcp-servers/{id}/test-connection`** — connects, discovers tools, returns them all with `approval_status: "pending"`:
```json
[{ "id": "...", "tool_name": "search_docs", "description": "...", "input_schema": {...}, "approval_status": "pending", "requires_hitl": false }]
```

**`PATCH /mcp-servers/{id}/tools/{tool_id}`** — approve/reject + set HITL requirement:
```json
{ "approval_status": "approved", "requires_hitl": true }
```
Only `approved` tools are ever bound to the model. `requires_hitl: true` means
every call to this specific tool triggers the approval flow above.

**`GET /mcp-servers`**, **`GET /mcp-servers/{id}/tools`**, **`DELETE /mcp-servers/{id}`** — standard CRUD/listing.

### Knowledge base picker (proxy)

**`GET /knowledge-bases`** — same response shape as knowledge-service's own
`GET /knowledge-bases` (see below); use this from the chat UI so the frontend
never needs knowledge-service's base URL directly.

### Media

**`POST /media/upload`** — `multipart/form-data`, field name `file`. Returns:
```json
{ "media_id": "uploads/local-user/3f0c...e1.png", "type": "image", "mime": "image/png", "url": "http://localhost:8101/api/v1/media/files/uploads/local-user/3f0c...e1.png" }
```
`415` for unsupported types, `413` above `MAX_MEDIA_UPLOAD_MB`. Stored in
chat-agent-service's own bucket (not file-processing-service, which only takes documents).

**`GET /media/files/{media_id}`** — serves the uploaded or generated file bytes
(usable directly as an `<img>`/`<audio>` `src`; no auth, keys are unguessable).

---

## file-processing-service

Talk to this directly for a "my files" management screen, or to show upload/
processing progress.

**`POST /files`** — `multipart/form-data`, field name `file`. Supported: `.docx`, `.pdf`, `.xlsx`/`.xlsm`, `.md`/`.markdown`. Max size: 100MB (`MAX_UPLOAD_SIZE_MB`).
```json
{ "file": { "id": "...", "filename": "report.pdf", "mime": "application/pdf", "file_type": "pdf", "size_bytes": 48213, "status": "uploaded", "error": null, "created_at": "...", "updated_at": "..." }, "job_id": "..." }
```

**`GET /files`** / **`GET /files/{id}`** — list / get metadata. `status` transitions: `uploaded → extracting → chunking → done` (or `failed`, with `error` populated).

**`DELETE /files/{id}`** — deletes the file, its chunks, and any extracted images from storage.

**`GET /files/{id}/chunks`** — the processed output (mainly consumed by knowledge-service, but useful for a "preview extracted content" UI):
```json
[{ "id": "...", "file_id": "...", "type": "text", "content": "...", "storage_key": null, "order_index": 0, "extra_metadata": {} }]
```
`type` is `"text"`, `"table"` (content is a markdown table), or `"image"`
(`storage_key` points at the extracted image; `content` is a short caption).

**`GET /files/{id}/download-url`** — presigned URL to the original raw file.

### Job progress (extraction/chunking)

**`GET /jobs/{job_id}/status`**
```json
{ "id": "...", "file_id": "...", "stage": "chunking", "error": null, "created_at": "...", "updated_at": "..." }
```

**`GET /jobs/{job_id}/stream`** — SSE, one event type only:
```
event: progress
data: {"stage": "extracting", "percent": 50, "message": "Extracted 42 raw blocks"}
```
`stage` progresses `extracting → chunking → done` (or `failed`, with the error
in `message`). If the job already finished by the time you connect, you get a
single immediate event with `percent: 100` instead of hanging.

```js
const es = new EventSource(`${FILE_BASE}/jobs/${jobId}/stream`); // GET-only, EventSource works fine here
es.addEventListener("progress", (e) => {
  const { stage, percent, message } = JSON.parse(e.data);
  updateProgressBar(stage, percent, message);
  if (stage === "done" || stage === "failed") es.close();
});
```
(Note: `EventSource` can't send an `Authorization` header. For an authenticated
deployment, either proxy this through your own backend or switch to a `fetch`-
based streaming reader like the `/chat/stream` example above.)

---

## knowledge-service

Talk to this directly for a "knowledge bases" management screen.

**`POST /knowledge-bases`**
```json
{ "name": "Product Docs", "description": "Public-facing documentation" }
```

**`GET /knowledge-bases`** / **`GET /knowledge-bases/{id}`** / **`PATCH /knowledge-bases/{id}`** / **`DELETE /knowledge-bases/{id}`** — standard CRUD. Delete also drops the underlying Qdrant collection.

**`GET /knowledge-bases/{id}/sources`** — files linked into this KB and their embedding status:
```json
[{ "id": "...", "knowledge_base_id": "...", "file_id": "...", "status": "done", "chunks_embedded": 87, "error": null }]
```
`status`: `pending → embedding → done` (or `failed`).

**`POST /knowledge-bases/{id}/ingest`** — link one or more already-uploaded files (from file-processing-service) into this KB and start embedding them:
```json
{ "file_ids": ["file-id-1", "file-id-2"] }
```
Response:
```json
{ "jobs": [{ "file_id": "file-id-1", "kb_source_id": "...", "job_id": "..." }] }
```
Watch each `job_id` via `GET /jobs/{id}/stream` (identical SSE shape to
file-processing-service's job stream above — same `{stage, percent, message}`
event, with `stage` progressing `embedding → done`/`failed`).

**`POST /search`** — mainly called internally by chat-agent-service, but usable directly for a "test my knowledge base" debug UI:
```json
{ "kb_ids": ["kb-id-1", "kb-id-2"], "query": "refund policy", "top_k": 6 }
```
```json
{ "results": [{ "score": 0.83, "chunk_id": "...", "file_id": "...", "knowledge_base_id": "kb-id-1", "content": "...", "type": "text" }] }
```
Results are merged and sorted by score across all given `kb_ids`.

---

## End-to-end example (upload → ingest → chat)

```js
const CHAT = "http://localhost:8001/api/v1";
const FILES = "http://localhost:8002/api/v1";
const KB = "http://localhost:8003/api/v1";
const auth = { Authorization: `Bearer ${token}` };

// 1. Upload a document
const form = new FormData();
form.append("file", fileInput.files[0]);
const { file } = await fetch(`${FILES}/files`, { method: "POST", headers: auth, body: form }).then(r => r.json());

// 2. Wait for extraction+chunking (poll or SSE — SSE shown here)
await new Promise((resolve) => {
  const es = new EventSource(`${FILES}/jobs/${file.job_id}/stream`); // omit auth in dev, proxy in prod
  es.addEventListener("progress", (e) => {
    const { stage } = JSON.parse(e.data);
    if (stage === "done" || stage === "failed") { es.close(); resolve(); }
  });
});

// 3. Create a knowledge base and ingest the file
const kb = await fetch(`${KB}/knowledge-bases`, {
  method: "POST", headers: { ...auth, "Content-Type": "application/json" },
  body: JSON.stringify({ name: "My Docs" }),
}).then(r => r.json());

const { jobs } = await fetch(`${KB}/knowledge-bases/${kb.id}/ingest`, {
  method: "POST", headers: { ...auth, "Content-Type": "application/json" },
  body: JSON.stringify({ file_ids: [file.id] }),
}).then(r => r.json());

// (again, wait for jobs[0].job_id via GET {KB}/jobs/{id}/stream until "done")

// 4. Chat, using that knowledge base
const resp = await fetch(`${CHAT}/chat/complete`, {
  method: "POST", headers: { ...auth, "Content-Type": "application/json" },
  body: JSON.stringify({
    content_blocks: [{ type: "text", text: "Summarize the document I just uploaded." }],
    knowledge_base_ids: [kb.id],
  }),
}).then(r => r.json());

console.log(resp.content_blocks); // assistant's answer, grounded in the uploaded doc
```

---

## Error format

All three services use FastAPI's default error shape:
```json
{ "detail": "Human-readable message" }
```
with the appropriate HTTP status code (`401` missing/invalid token, `404` not
found, `409`/`422` validation errors, `502` for an MCP connection failure,
`413` for an oversized upload, `415` for an unsupported file type).
