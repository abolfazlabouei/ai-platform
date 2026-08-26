# Build context MUST be the repo root (ai-platform/), not this directory, because
# this service depends on the local ../shared-schemas package. See docker-compose.yml
# `build: {context: ., dockerfile: chat-agent-service/Dockerfile}`.
FROM python:3.11-slim

WORKDIR /app

# Install shared-schemas first (rarely changes -> good layer caching)
COPY shared-schemas /shared-schemas
RUN pip install --no-cache-dir /shared-schemas

COPY chat-agent-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY chat-agent-service/ .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
