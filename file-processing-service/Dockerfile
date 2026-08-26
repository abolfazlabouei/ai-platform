# Build context MUST be the repo root (ai-platform/), because this service depends
# on the local ../shared-schemas package (currently only used for the Chunk contract
# type-hint; kept for consistency and future direct imports).
FROM python:3.11-slim

WORKDIR /app

# System deps needed by PyMuPDF/psycopg2 wheels on slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY shared-schemas /shared-schemas
RUN pip install --no-cache-dir /shared-schemas

COPY file-processing-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY file-processing-service/ .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
