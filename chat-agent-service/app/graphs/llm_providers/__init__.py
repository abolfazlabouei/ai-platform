"""
Model factory: builds a LangChain chat model instance from an Agent's/ad-hoc request's
model_config, so llm_node doesn't need to know about provider-specific SDKs.
Add a new branch here to support a new provider — nothing else in the graph changes.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings


def build_chat_model(provider: str, model: str, temperature: float = 0.7) -> BaseChatModel:
    provider = (provider or settings.DEFAULT_MODEL_PROVIDER).lower()

    if provider == "anthropic":
        ...

    if provider == "openai":
        ...

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or "google/gemma-2-27b-it", 
            temperature=temperature,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )

    raise ValueError(f"Unsupported model provider: {provider}")
