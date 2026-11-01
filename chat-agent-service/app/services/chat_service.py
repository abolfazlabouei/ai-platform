"""
chat_service: the central orchestration point for every turn, whether it's ad-hoc
chat (mcp/kb chosen on the fly) or agent chat (mcp/kb/prompt/model fixed on the Agent).

Responsibilities:
  1. Resolve RuntimeConfig (system prompt, model, approved+bound MCP tools, hitl map,
     knowledge base ids) from either the Agent row or the ad-hoc request payload.
  2. Persist the incoming user message.
  3. Invoke the compiled LangGraph (stream or complete) with that RuntimeConfig.
  4. Persist the resulting assistant message(s), including any generated images.
  5. Handle resuming an interrupted graph after a tool-approval decision.

Both /chat/* (ad-hoc) and /agents/{id}/chat/* endpoints funnel through this one
service so there is exactly one code path for "run a turn".
"""
from __future__ import annotations

import uuid
from typing import Any
from collections.abc import AsyncIterator
from app.observability.langfuse_client import get_langfuse_config_extras
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.graphs.builder import get_compiled_graph
from app.graphs.state import RuntimeConfig
from app.mcp_manager.client_pool import McpClientPool, to_tool_schema
from app.mcp_manager.tool_registry import build_hitl_map, get_approved_tools
from app.models.agent import Agent
from app.models.mcp_server import McpServer
from app.models.message import MessageRole
from app.repositories.mcp_repo import McpRepo
from app.services.conversation_service import ConversationService
from app.services.skill_service import SkillService
from app.skills.catalog import SKILL_RUN_SCRIPT_TOOL, build_catalog
from app.services.title_service import generate_title


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_service = ConversationService(db)
        self.mcp_repo = McpRepo(db)

    async def _build_runtime_config(
        self,
        conversation_id: uuid.UUID,
        user_id: str,
        agent: Agent | None,
        mcp_server_ids: list[str],
        knowledge_base_ids: list[str],
        model_provider: str | None,
        model_name: str | None,
        system_prompt_override: str | None,
        skill_refs: list[dict] | None = None,
    ) -> RuntimeConfig:
        approved_tools = await get_approved_tools(self.db, mcp_server_ids)
        hitl_map = build_hitl_map(approved_tools)

        # Skills: an agent always uses its own; ad-hoc chat uses the request's. Missing/disabled ones are skipped.
        skills = await SkillService(self.db).resolve_for_runtime(
            user_id, agent.skill_ids if agent else skill_refs
        )
        if skills:
            hitl_map.setdefault(SKILL_RUN_SCRIPT_TOOL, True)  # scripts need approval until trusted

        servers: list[McpServer] = []
        for server_id in {t.mcp_server_id for t in approved_tools}:
            server = await self.mcp_repo.get_server(server_id)
            if server:
                servers.append(server)

        pool = McpClientPool()
        approved_names = {t.tool_name for t in approved_tools}
        # plain-data schemas, not tool objects: the runtime is checkpointed (see to_tool_schema)
        bound_tools = (
            [
                to_tool_schema(t)
                for t in await pool.as_langchain_tools(
                    servers, approved_names, conversation_id=str(conversation_id), user_id=user_id
                )
            ]
            if servers
            else []
        )

        if agent:
            provider = model_provider or agent.model_config_json.get("provider", settings.DEFAULT_MODEL_PROVIDER)
            model = model_name or agent.model_config_json.get("model", settings.DEFAULT_MODEL_NAME)
            temperature = agent.model_config_json.get("temperature", 0.7)
            system_prompt = system_prompt_override or agent.system_prompt
        else:
            provider = model_provider or settings.DEFAULT_MODEL_PROVIDER
            model = model_name or settings.DEFAULT_MODEL_NAME
            temperature = 0.7
            system_prompt = system_prompt_override or "You are a helpful assistant."

        return RuntimeConfig(
            conversation_id=str(conversation_id),
            user_id=user_id,
            agent_id=str(agent.id) if agent else None,
            model_provider=provider,
            model_name=model,
            model_temperature=temperature,
            system_prompt=system_prompt,
            knowledge_base_ids=knowledge_base_ids,
            bound_tools=bound_tools,
            tool_hitl_map=hitl_map,
            skills=skills,
            skills_catalog=build_catalog(skills),
        )

    async def run_turn(
        self,
        conversation_id: uuid.UUID,
        user_id: str,
        content_blocks: list[dict],
        agent: Agent | None,
        mcp_server_ids: list[str],
        knowledge_base_ids: list[str],
        model_provider: str | None = None,
        model_name: str | None = None,
        system_prompt_override: str | None = None,
        skill_refs: list[dict] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Async generator yielding raw LangGraph stream events. The API layer's SSE
        module wraps this into `event: ...\\ndata: ...` frames; /chat/complete just
        drains it and returns the final state.
        """
        conversation = await self.conversation_service.conv_repo.get(conversation_id)

        await self.conversation_service.record_message(
            conversation_id, MessageRole.USER, content_blocks
        )

        # Applies identically to ad-hoc and agent conversations — the only trigger
        # is "this conversation doesn't have a title yet" (checked inside
        # set_title_if_empty), not which mode the conversation is in. No-ops with
        # zero LLM calls on every turn after the first.
        if conversation is not None:
            await self._maybe_generate_title(conversation, content_blocks)

        runtime = await self._build_runtime_config(
            conversation_id,
            user_id,
            agent,
            mcp_server_ids,
            knowledge_base_ids,
            model_provider,
            model_name,
            system_prompt_override,
            skill_refs,
        )

        graph = await get_compiled_graph()
        config = {
            "configurable": {"thread_id": str(conversation_id)},
            **get_langfuse_config_extras(
                conversation_id=str(conversation_id),
                user_id=user_id,
                agent_id=str(agent.id) if agent else None,
            ),
        }
        initial_state = {"_incoming_blocks": content_blocks, "runtime": runtime}

        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            yield event

        final_state = await graph.aget_state(config)
        await self._persist_assistant_output(conversation_id, final_state.values)

    async def _maybe_generate_title(self, conversation, content_blocks: list[dict]) -> None:
        """
        Generates and persists a title from the user's message, but only if the
        conversation doesn't already have one — this is what makes it "first
        message only" without needing to separately track message counts:
        set_title_if_empty is a guaranteed no-op (no LLM call) once a title exists.
        """
        if conversation.title is not None:
            return
        title = await generate_title(content_blocks)
        await self.conversation_service.set_title_if_empty(conversation, title)

    async def resume_tool_approval(
        self, conversation_id: uuid.UUID, decisions: dict[str, bool]
    ) -> AsyncIterator[dict[str, Any]]:
        """Resumes a graph paused at hitl_gate's interrupt() with the user's approve/reject decisions."""
        conversation = await self.conversation_service.conv_repo.get(conversation_id)
        graph = await get_compiled_graph()
        config = {
            "configurable": {"thread_id": str(conversation_id)},
            **get_langfuse_config_extras(
                conversation_id=str(conversation_id),
                user_id=conversation.user_id if conversation else "unknown",
                agent_id=str(conversation.agent_id) if conversation and conversation.agent_id else None,
            ),
        }

        async for event in graph.astream_events(Command(resume=decisions), config=config, version="v2"):
            yield event

        final_state = await graph.aget_state(config)
        await self._persist_assistant_output(conversation_id, final_state.values)

    async def _persist_assistant_output(self, conversation_id: uuid.UUID, state_values: dict) -> None:
        messages = state_values.get("messages", [])
        if not messages:
            return
        last_message = messages[-1]
        if getattr(last_message, "type", None) != "ai":
            return

        blocks: list[dict] = []
        content = last_message.content
        if isinstance(content, str):
            blocks.append({"type": "text", "text": content})
        else:
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    blocks.append({"type": "text", "text": part["text"]})

        blocks.extend(state_values.get("generated_images", []))

        await self.conversation_service.record_message(conversation_id, MessageRole.ASSISTANT, blocks)
