#!/usr/bin/env bash
# Runs Alembic migrations before starting the API server. Only the API container
# (not the Celery worker, which overrides CMD via docker-compose's `command:`)
# runs this, avoiding two containers racing to apply migrations concurrently.
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
