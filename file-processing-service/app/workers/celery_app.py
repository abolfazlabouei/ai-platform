"""
Celery application config. Broker + result backend both point at Redis.
A single queue `file_processing` is used; run workers with:
    celery -A app.workers.celery_app worker -Q file_processing -l info --concurrency=4
Concurrency is scaled independently from the FastAPI/uvicorn process, which is the
whole point of offloading extraction/chunking here — heavy CPU/IO work never blocks
the HTTP layer, so it can keep serving upload requests and SSE progress streams for
~100 concurrent users while a smaller pool of workers grinds through the actual files.
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "file_processing_service",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue="file_processing",
    task_track_started=True,
    task_acks_late=True,  # re-deliver to another worker if one crashes mid-file
    worker_prefetch_multiplier=1,  # don't let one worker hoard multiple large-file jobs
    task_time_limit=60 * 30,  # hard kill after 30 minutes (very large files)
    task_soft_time_limit=60 * 25,
)
