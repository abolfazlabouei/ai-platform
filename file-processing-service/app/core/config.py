"""Centralized settings for file-processing-service, loaded from env / .env."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "file-processing-service"
    ENV: Literal["dev", "staging", "prod"] = "dev"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/file_processing_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/2"
    CELERY_BROKER_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- Object storage (raw uploads + extracted images) ---
    S3_ENDPOINT: str = "http://minio:9000"
    S3_BUCKET_RAW: str = "raw-files"
    S3_BUCKET_IMAGES: str = "extracted-images"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_PUBLIC_BASE_URL: str = "http://localhost:9000"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str | None = None

    # --- TEMPORARY: auth disabled for local/demo use (see app/core/security.py) ---
    AUTH_DISABLED: bool = True
    AUTH_DISABLED_USER_ID: str = "local-user"

    # --- Chunking defaults ---
    TEXT_CHUNK_SIZE: int = 1000
    TEXT_CHUNK_OVERLAP: int = 150
    MAX_TABLE_ROWS_PER_CHUNK: int = 30

    MAX_UPLOAD_SIZE_MB: int = 200
    # Max chars of one table chunk (header row is repeated in every chunk). Keeps
    # wide Excel sheets under the embedding model's input limit.
    MAX_TABLE_CHUNK_CHARS: int = 3500

    # --- Vision model (image captioning + OCR of scanned / garbled PDF pages) ---
    # Any OpenAI-compatible /chat/completions endpoint that accepts image input
    # (OpenRouter works). Leave VISION_API_KEY empty to disable: images are then
    # skipped instead of being indexed as useless "[image]" placeholders.
    VISION_API_KEY: str | None = None
    VISION_BASE_URL: str = "https://openrouter.ai/api/v1"
    VISION_MODEL: str = "google/gemini-2.0-flash-001"
    VISION_OUTPUT_LANGUAGE: str = "Persian"
    VISION_TIMEOUT_SECONDS: int = 120
    VISION_CONCURRENCY: int = 4
    VISION_MAX_RETRIES: int = 2
    # Images smaller than this (either side, px) are icons/lines/bullets — skipped.
    IMAGE_MIN_SIDE_PX: int = 80
    # PDF OCR via vision model:
    #   never  — text layer only
    #   auto   — OCR pages that have (almost) no text layer, or whose Persian/Arabic
    #            text layer is detected as garbled (broken letter order/spacing)
    #   always — OCR every page (most robust for Persian PDFs; slower/costlier)
    PDF_OCR_MODE: Literal["never", "auto", "always"] = "auto"
    PDF_OCR_DPI: int = 150
    PDF_OCR_MIN_TEXT_CHARS: int = 40

    # Celery hard time limit per file (vision OCR of large PDFs takes a while)
    FILE_TASK_TIME_LIMIT_SECONDS: int = 60 * 120


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
