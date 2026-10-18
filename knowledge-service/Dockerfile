# Build context MUST be the repo root (ai-platform/) — this service depends on the
# local ../shared-schemas package (used for the Chunk contract type-hint).
FROM python:3.11-slim

WORKDIR /app

COPY shared-schemas /shared-schemas
RUN pip install --no-cache-dir /shared-schemas

COPY knowledge-service/requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip
RUN python -m pip install --no-cache-dir --timeout 120 --retries 10 --resume-retries 20 torch --extra-index-url https://download.pytorch.org/whl/cpu
RUN python -m pip install --no-cache-dir --timeout 120 --retries 10 --resume-retries 20 -r requirements.txt

COPY knowledge-service/ .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
