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

    # --- Object storage (chat media: user image/audio uploads + generated images) ---
    S3_ENDPOINT: str = "http://minio:9000"
    S3_BUCKET_GENERATED: str = "generated-media"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    # Base URL clients use to fetch chat media; served by GET /api/v1/media/files/{key}
    MEDIA_PUBLIC_BASE_URL: str = "http://localhost:8101/api/v1/media/files"
    MAX_MEDIA_UPLOAD_MB: int = 20

    # --- Auth ---
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str | None = None

    # --- TEMPORARY: auth disabled for local/demo use (see app/core/security.py) ---
    AUTH_DISABLED: bool = True
    AUTH_DISABLED_USER_ID: str = "local-user"

    # --- LLM providers (API keys resolved per-agent/model_config, these are defaults) ---
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    DEFAULT_MODEL_PROVIDER: str = "openrouter"
    # text + image + audio in, text out
    DEFAULT_MODEL_NAME: str = "qwen/qwen3.8-omni-flash"

    # --- Image generation (exposed to the chat model as the generate_image tool) ---
    IMAGE_GEN_ENABLED: bool = True
    IMAGE_GEN_MODEL: str = "google/gemini-nano-banana-2.1"
    IMAGE_GEN_TIMEOUT_SECONDS: int = 120

    # --- MCP ---
    MCP_CONNECT_TIMEOUT_SECONDS: int = 15
    MCP_TOOL_CALL_TIMEOUT_SECONDS: int = 60
    # Shared with code-sandbox-service (MCP servers with auth_config {"type": "sandbox"}):
    # the key authenticates this service; the context secret signs the per-conversation JWT.
    SANDBOX_SHARED_SECRET: str = ""
    SANDBOX_CONTEXT_SECRET: str = ""
    # REST base URL of code-sandbox-service, used by skill_run_script (SKILLS_SCRIPTS_ENABLED)
    SANDBOX_BASE_URL: str = "http://code-sandbox-service:8000"
    SANDBOX_REQUEST_TIMEOUT_SECONDS: int = 180

    # --- Streaming / concurrency ---
    SSE_KEEPALIVE_SECONDS: int = 15
    MAX_HISTORY_MESSAGES_LOADED: int = 50

    # --- RAG ---
    RAG_TOP_K: int = 8
    # Hard cap on retrieved text injected into the prompt. Must fit the chat model's
    # context window together with history (Persian ~1 token/char). gemma-2-27b-it has
    # only an 8k-token window — use ~5000 there, or a long-context model.
    RAG_MAX_CONTEXT_CHARS: int = 12000
    # Rewrite follow-up questions ("و قیمتش؟") into standalone search queries using
    # the conversation history before searching. Falls back to the raw question on error.
    RAG_QUERY_REWRITE: bool = True
    RAG_DEBUG: bool = True
    
    # --- Agent skills (see app/skills/) ---
    SKILLS_BUCKET: str = "skills"
    SKILLS_MAX_PER_AGENT: int = 20
    SKILLS_MAX_ZIP_MB: int = 10
    SKILLS_MAX_UNCOMPRESSED_MB: int = 25
    SKILLS_MAX_FILES: int = 100
    SKILLS_MAX_BODY_KB: int = 50
    SKILLS_MAX_ASSET_MB: int = 5
    # Level-1 catalog budget in the system prompt; skills past it are left out (with a note).
    SKILLS_CATALOG_MAX_CHARS: int = 16000
    SKILLS_READ_FILE_MAX_BYTES: int = 64 * 1024
    # Phase 2 switch: skill_run_script via code-sandbox-service.
    SKILLS_SCRIPTS_ENABLED: bool = False
    # Browser-reachable S3 endpoint used only to sign download links for binary skill files.
    S3_PUBLIC_BASE_URL: str = "http://localhost:9010"
    SKILLS_FILE_URL_TTL_SECONDS: int = 3600

    # --- Observability (Langfuse) ---
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
