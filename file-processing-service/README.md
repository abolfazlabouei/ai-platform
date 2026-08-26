# file-processing-service

Uploads, extracts, and chunks documents (docx/pdf/xlsx/markdown), including tables
and embedded images. Implements everything in `../ARCHITECTURE.md` section 3.

## Architecture within this service

```
FastAPI (upload/status/SSE)          Celery worker (extract + chunk)
        │                                      │
        ├─ stores raw bytes ───────────────────┤  reads raw bytes
        │  in object storage                   │  from object storage
        │                                       │
        ├─ creates File + Job rows              ├─ extractors/*.py -> raw blocks
        │  (status=uploaded/queued)              │  (paragraph/table/image)
        │                                       │
        ├─ enqueues Celery task ────────────────┤  chunkers/*.py -> Chunk rows
        │  process_file.delay(...)              │  (text/table/image, ordered)
        │                                       │
        └─ GET /jobs/{id}/stream ◄──────────────┘  publishes progress to
           (SSE, subscribes to Redis)               Redis channel job:{id}
```

The HTTP layer never blocks on extraction/chunking — it only stores the file,
enqueues a task, and (optionally) streams progress from Redis. This is what lets
it stay responsive with ~100 concurrent uploads while a separately-scaled Celery
worker pool does the CPU/IO-heavy work.

## Run locally (Docker)

```bash
cd ai-platform
cp file-processing-service/.env.example file-processing-service/.env
docker compose up file-processing-service file-processing-worker postgres redis minio
```

Open http://localhost:8002/docs for interactive API docs.

## Run locally (without Docker)

```bash
cd ai-platform
pip install -e shared-schemas
cd file-processing-service
pip install -r requirements.txt
cp .env.example .env

# terminal 1 — API
uvicorn app.main:app --reload --port 8002

# terminal 2 — worker
celery -A app.workers.celery_app worker -Q file_processing -l info --concurrency=4
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/files` | Upload a file (multipart). Returns the `File` row + a `job_id`. |
| GET | `/api/v1/files` | List your uploaded files. |
| GET | `/api/v1/files/{id}` | File metadata + status (`uploaded → extracting → chunking → done/failed`). |
| DELETE | `/api/v1/files/{id}` | Deletes the file, its chunks, and any extracted images from storage. |
| GET | `/api/v1/files/{id}/chunks` | Returns processed chunks in document order. **This is what knowledge-service calls during ingest.** |
| GET | `/api/v1/jobs/{id}/status` | Current stage of the processing job. |
| GET | `/api/v1/jobs/{id}/stream` | SSE stream of live progress (`{stage, percent, message}`), fed by Redis pub/sub. |

## Supported formats and what gets extracted

| Format | Paragraphs | Tables | Embedded images |
|---|---|---|---|
| `.docx` | ✅ | ✅ (row/column structure preserved) | ✅ (via raw zip walk of `word/media/`, not just python-docx runs) |
| `.pdf` | ✅ (per page) | ✅ (via PyMuPDF `find_tables()`) | ✅ (via PyMuPDF `extract_image`) |
| `.xlsx` / `.xlsm` | — | ✅ (each sheet, pre-batched by row count) | — |
| `.md` / `.markdown` | ✅ (headings kept as `#`-prefixed blocks) | ✅ | — |

Chunking rules:
- Consecutive paragraphs are merged and split via a recursive splitter (`TEXT_CHUNK_SIZE`/`TEXT_CHUNK_OVERLAP`).
- Tables become markdown-table chunks; oversized tables are split every `MAX_TABLE_ROWS_PER_CHUNK` rows, repeating the header row in each chunk so no chunk loses column context.
- Images are uploaded to the `extracted-images` bucket and represented as an image-type chunk with a short caption placeholder (a vision-captioning step can be added inside `chunkers/image_chunker.py` without touching anything else).

## Concurrency notes (~100 simultaneous users)

- `task_acks_late=True` + `worker_prefetch_multiplier=1`: a crashed worker's in-flight file gets redelivered to another worker, and no single worker hoards multiple large files at once.
- Redis pub/sub (not an in-process queue) decouples publishers (Celery workers, possibly on separate machines) from subscribers (FastAPI instances behind a load balancer).
- Scale `file-processing-worker` replicas independently of `file-processing-service` replicas in docker-compose/k8s.

## Not yet included

- Alembic revisions are not pre-generated — run `alembic revision --autogenerate -m "init"` once Postgres is reachable, then `alembic upgrade head`.
- Virus/malware scanning on upload.
- Image captioning (currently a placeholder string — see `chunkers/image_chunker.py`).
- OCR for scanned/image-only PDFs (current PDF extractor only pulls native text layers).
- Ownership checks on `GET/DELETE /files/{id}` (any authenticated caller can currently read/delete any file by id — add a `file.user_id == current_user.user_id` check before production use). `POST /files` does correctly scope the upload to the caller.

## Inter-service auth note

`chat-agent-service`'s media proxy (`POST /media/upload`) forwards the caller's
bearer token to this service's `POST /files`, since both services trust the same
`JWT_SECRET`. `GET /files/{id}/download-url` is called without forwarding a token
(resolving an id to a presigned URL is treated as non-sensitive) — tighten this
alongside the ownership-check gap above if that assumption doesn't hold for your
deployment.
