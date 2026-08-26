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

    # --- Chunking defaults ---
    TEXT_CHUNK_SIZE: int = 1000
    TEXT_CHUNK_OVERLAP: int = 150
    MAX_TABLE_ROWS_PER_CHUNK: int = 30

    MAX_UPLOAD_SIZE_MB: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
