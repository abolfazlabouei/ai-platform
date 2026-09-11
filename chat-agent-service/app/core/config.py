"""
Centralized application settings, loaded from environment variables / .env.
All other modules should import `settings` from here instead of reading os.environ directly.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Service identity ---
    SERVICE_NAME: str = "chat-agent-service"
    ENV: Literal["dev", "staging", "prod"] = "dev"
    DEBUG: bool = True

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chat_agent_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- Redis (pub/sub for job/HITL notifications, rate limiting) ---
    REDIS_URL: str = "redis://localhost:6379/1"

    # --- Checkpointer ---
    # If false, falls back to an in-memory LangGraph checkpointer (dev only —
    # HITL resume / durability across restarts will NOT work).
    USE_POSTGRES_CHECKPOINTER: bool = True

    # --- Downstream services ---
    FILE_SERVICE_URL: str = "http://file-processing-service:8000"
    KNOWLEDGE_SERVICE_URL: str = "http://knowledge-service:8000"

    # --- Object storage (for referencing generated images uploaded by output_formatter) ---
    S3_ENDPOINT: str = "http://minio:9000"
    S3_BUCKET_GENERATED: str = "generated-media"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_PUBLIC_BASE_URL: str = "http://localhost:9000/generated-media"

    # --- Auth & OAuth ---
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str | None = None
    TOKEN_ENCRYPTION_KEY: str | None = None  # base64 Fernet key, see app/core/encryption.py
    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = None
    GOOGLE_OAUTH_REDIRECT_BASE_URL: str = "http://localhost:8101"  # externally-reachable base URL for this service; used to build the redirect_uri
    OAUTH_SUCCESS_REDIRECT_URL: str | None = None

    # --- LLM providers (API keys resolved per-agent/model_config, these are defaults) ---
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    DEFAULT_MODEL_PROVIDER: str = "anthropic"
    DEFAULT_MODEL_NAME: str = "claude-sonnet-4-6"

    # --- MCP ---
    MCP_CONNECT_TIMEOUT_SECONDS: int = 15
    MCP_TOOL_CALL_TIMEOUT_SECONDS: int = 60

    # --- Streaming / concurrency ---
    SSE_KEEPALIVE_SECONDS: int = 15
    MAX_HISTORY_MESSAGES_LOADED: int = 50
    
    # --- Observability (Langfuse) ---
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    
    CLINIC_API_BASE_URL: str = "https://api.doctor-laser.ir"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
