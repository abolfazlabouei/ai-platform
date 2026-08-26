"""
Celery app config for knowledge-service. Single queue `embedding`. Run workers with:
    celery -A app.workers.celery_app worker -Q embedding -l info --concurrency=4
Kept as its own broker/queue (separate from file-processing-service's `file_processing`
queue) so embedding throughput can be scaled independently of extraction/chunking
throughput — they have very different bottlenecks (network-bound API calls to an
embedding provider vs CPU-bound parsing).
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "knowledge_service",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.embed_tasks"],
)

celery_app.conf.update(
    task_default_queue="embedding",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=60 * 30,
    task_soft_time_limit=60 * 25,
)
