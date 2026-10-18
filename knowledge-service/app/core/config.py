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

    # --- Embedding provider ---
    EMBEDDING_PROVIDER: Literal["openai", "anthropic_voyage"] = "openai"
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_TIMEOUT_SECONDS: float = 120.0
    EMBEDDING_CONNECT_TIMEOUT_SECONDS: float = 30.0
    EMBEDDING_MAX_RETRIES: int = 8

    DEFAULT_SEARCH_TOP_K: int = 6

    # --- Hybrid search (dense + lexical, fused via RRF) ---
    DENSE_TOP_K: int = 50
    LEXICAL_TOP_K: int = 50
    LEXICAL_BACKEND: Literal["postgres_fts", "bm25"] = "postgres_fts"
    LEXICAL_PHRASE_BOOST: float = 2.0

    RRF_K: int = 60
    RRF_DENSE_WEIGHT: float = 1.0
    RRF_LEXICAL_WEIGHT: float = 1.5

    # --- Reranking (cross-encoder on the fused top-N) ---
    ENABLE_RERANK: bool = True
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RERANK_CANDIDATE_K: int = 25  # how many fused results are fed to the reranker
    RERANK_BATCH_SIZE: int = 32

    RERANK_BACKEND: Literal["local", "openrouter_api"] = "local"
    RERANK_API_KEY: str | None = None
    RERANK_API_URL: str = "https://openrouter.ai/api/v1/rerank"
    RERANK_API_MODEL: str = "cohere/rerank-v3.5"
    RERANK_API_TIMEOUT_SECONDS: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
