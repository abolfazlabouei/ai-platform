"""Centralized settings for knowledge-service, loaded from env / .env."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "knowledge-service"
    ENV: Literal["dev", "staging", "prod"] = "dev"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/knowledge_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/3"
    CELERY_BROKER_URL: str = "redis://localhost:6379/3"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/3"

    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_COLLECTION_PREFIX: str = "kb_"  # one Qdrant collection per knowledge base: kb_{kb_id}

    FILE_SERVICE_URL: str = "http://file-processing-service:8000"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str | None = None

    # --- TEMPORARY: auth disabled for local/demo use (see app/core/security.py) ---
    AUTH_DISABLED: bool = True
    AUTH_DISABLED_USER_ID: str = "local-user"

    # --- Embedding provider ---
    EMBEDDING_PROVIDER: Literal["openai", "anthropic_voyage"] = "openai"
    EMBEDDING_BASE_URL: str | None = None 
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_MAX_RETRIES: int = 3
    # Persian is ~1 token/char for OpenAI tokenizers; 6000 chars stays under 8191 tokens.
    EMBEDDING_MAX_INPUT_CHARS: int = 6000

    DEFAULT_SEARCH_TOP_K: int = 6

    # --- Hybrid search (dense Qdrant + lexical Postgres FTS, fused via RRF) ---
    HYBRID_SEARCH_ENABLED: bool = True
    DENSE_TOP_K: int = 50
    LEXICAL_TOP_K: int = 50
    LEXICAL_PHRASE_BOOST: float = 2.0
    RRF_K: int = 60
    RRF_DENSE_WEIGHT: float = 1.0
    RRF_LEXICAL_WEIGHT: float = 1.5

    # --- Reranking (optional; off by default) ---
    # "openrouter_api" needs only RERANK_API_KEY. "local" needs  (pulls in torch) and a multilingual model for Persian.
    ENABLE_RERANK: bool = False
    RERANK_BACKEND: Literal["local", "openrouter_api"] = "openrouter_api"
    RERANK_CANDIDATE_K: int = 25
    RERANK_MODEL: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"  # local backend
    RERANK_BATCH_SIZE: int = 32
    RERANK_API_KEY: str | None = None
    RERANK_API_URL: str = "https://openrouter.ai/api/v1/rerank"
    RERANK_API_MODEL: str = "cohere/rerank-v3.5"
    RERANK_API_TIMEOUT_SECONDS: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
