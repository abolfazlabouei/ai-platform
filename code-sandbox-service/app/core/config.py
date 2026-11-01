"""Centralized settings for code-sandbox-service, loaded from env / .env."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "code-sandbox-service"
    ENV: Literal["dev", "staging", "prod"] = "dev"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sandbox_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/5"

    # --- Docker / sandbox runtime ---
    # The docker SDK reads DOCKER_HOST itself (docker.from_env); kept here for documentation.
    DOCKER_HOST: str = "unix:///var/run/docker.sock"
    # gVisor by default. A KVM host can switch to "kata" / "runsc-kvm" with no code change.
    SANDBOX_RUNTIME: str = "runsc"
    SANDBOX_IMAGE_PYTHON: str = "ai-platform-sandbox-python:1"

    # --- Per-container limits (see app/sandbox/spec.py) ---
    SANDBOX_MEMORY: str = "1g"
    SANDBOX_CPUS: float = 1.0
    SANDBOX_PIDS_LIMIT: int = 128
    SANDBOX_WORKSPACE_SIZE: str = "512m"
    SANDBOX_TMP_SIZE: str = "64m"
    SANDBOX_NOFILE: int = 1024
    SANDBOX_MAX_FILE_BYTES: int = 256 * 1024 * 1024

    # --- Execution limits ---
    SANDBOX_MAX_EXEC_SECONDS: int = 120
    SANDBOX_DEFAULT_EXEC_SECONDS: int = 30
    SANDBOX_MAX_OUTPUT_BYTES: int = 64 * 1024
    SANDBOX_MAX_CODE_BYTES: int = 100 * 1024
    # Host-side grace on top of the in-container `timeout` before the whole container is killed.
    SANDBOX_HOST_TIMEOUT_GRACE_SECONDS: int = 5

    # --- Session lifecycle ---
    SANDBOX_IDLE_TTL_SECONDS: int = 20 * 60
    SANDBOX_MAX_LIFETIME_SECONDS: int = 4 * 60 * 60
    SANDBOX_REAPER_INTERVAL_SECONDS: int = 60
    SANDBOX_WARM_POOL_SIZE: int = 2
    SANDBOX_MAX_SESSIONS: int = 20
    SANDBOX_MAX_SESSIONS_PER_USER: int = 3
    # How long an exec waits for another exec in the same session to finish.
    SANDBOX_LOCK_WAIT_SECONDS: int = 10

    # --- Abuse limits ---
    SANDBOX_RATE_LIMIT_PER_MINUTE: int = 30
    SANDBOX_DAILY_CPU_SECONDS_PER_USER: int = 3600

    # --- Files ---
    SANDBOX_MAX_IMPORT_MB: int = 100
    SANDBOX_MAX_WRITE_BYTES: int = 5 * 1024 * 1024
    SANDBOX_MAX_READ_BYTES: int = 64 * 1024
    SANDBOX_MAX_ARTIFACTS: int = 20
    SANDBOX_MAX_ARTIFACT_BYTES: int = 20 * 1024 * 1024

    # --- Service-to-service auth (see app/core/security.py) ---
    SANDBOX_SHARED_SECRET: str = "change-me"
    SANDBOX_CONTEXT_SECRET: str = "change-me-too"

    # --- Platform services ---
    FILE_SERVICE_URL: str = "http://file-processing-service:8000"

    # --- Object storage (artifacts) ---
    S3_ENDPOINT: str = "http://minio:9000"
    S3_BUCKET_ARTIFACTS: str = "sandbox-artifacts"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    # Presigned URLs are signed against this host so a browser can open them.
    S3_PUBLIC_BASE_URL: str = "http://localhost:9010"
    SANDBOX_ARTIFACT_URL_TTL: int = 24 * 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
