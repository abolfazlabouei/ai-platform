"""
Langfuse integration for LangGraph tracing.

Langfuse's Python SDK v3+ changed its LangChain integration API: session_id,
user_id, and tags are no longer CallbackHandler constructor arguments (that
was the deprecated v2 API, `from langfuse.callback import CallbackHandler`).
In the current SDK (`from langfuse.langchain import CallbackHandler`), the
handler takes no per-request identity args at all — session_id/user_id/tags
must instead be passed as `langfuse_session_id`/`langfuse_user_id`/
`langfuse_tags` keys inside the LangChain/LangGraph `config["metadata"]` dict
on every invocation. This module returns exactly that shape, ready to be
merged into the `config` dict passed to `graph.astream_events(...)`.
"""
from __future__ import annotations

from app.core.config import settings


def get_langfuse_config_extras(
    conversation_id: str, user_id: str, agent_id: str | None = None
) -> dict:
    """
    Returns {} (no-op) if Langfuse is disabled. Otherwise returns
    {"callbacks": [...], "metadata": {...}} to be merged into the graph's
    `config` dict — e.g. `config = {**config, **get_langfuse_config_extras(...)}`.
    """
    if not settings.LANGFUSE_ENABLED:
        return {}

    from langfuse.langchain import CallbackHandler

    # CallbackHandler() reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
    # LANGFUSE_HOST from the environment automatically — no args needed here.
    handler = CallbackHandler()

    return {
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": conversation_id,
            "langfuse_user_id": user_id,
            "langfuse_tags": [f"agent:{agent_id}"] if agent_id else ["ad_hoc"],
        },
    }