"""
Agent CRUD + per-agent chat endpoints. /agents/{id}/chat/stream and /complete are the
exact same underlying primitive an ad-hoc chat uses — the only difference is that the
agent's own system_prompt/model/mcp/kb config is used instead of per-request choices.

These two endpoints are also the contract the future multi-agent-orchestrator-service
calls to treat this agent as a sub-agent/tool (see AgentCard.invoke_url/stream_url and
`is_composable`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate
from app.schemas.chat import ChatCompleteResponse, ChatRequest
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.streaming.sse import to_sse

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_agent_out(agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        system_prompt=agent.system_prompt,
        model_config=agent.model_config_json,
        mcp_server_ids=agent.mcp_server_ids,
        knowledge_base_ids=agent.knowledge_base_ids,
        tool_policy=agent.tool_policy,
        capabilities=agent.capabilities,
        is_composable=agent.is_composable,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("", response_model=AgentOut)
async def create_agent(
    body: AgentCreate, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    service = AgentService(db)
    agent = await service.create(
        user_id=user.user_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model_config=body.model_config_.model_dump(),
        mcp_server_ids=[str(i) for i in body.mcp_server_ids],
        knowledge_base_ids=body.knowledge_base_ids,
        tool_policy=[{**t.model_dump(), "server_id": str(t.server_id)} for t in body.tool_policy],
        capabilities=body.capabilities,
        is_composable=body.is_composable,
    )
    return _to_agent_out(agent)


@router.get("", response_model=list[AgentOut])
async def list_agents(
    is_composable: bool | None = None,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    service = AgentService(db)
    # `is_composable=true` is how the future orchestrator discovers callable sub-agents.
    agents = await service.list_composable() if is_composable else await service.list_for_user(user.user_id)
    return [_to_agent_out(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = AgentService(db)
    agent = await service.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return _to_agent_out(agent)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate, db: AsyncSession = Depends(get_db)):
    service = AgentService(db)
    agent = await service.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    fields = body.model_dump(exclude_unset=True, by_alias=False)
    if "model_config_" in fields:
        # model_dump() already recursively converts nested BaseModel fields (like
        # ModelConfigIn) into plain dicts — calling .model_dump() on them again
        # fails with AttributeError since dicts don't have that method.
        fields["model_config"] = fields.pop("model_config_")
    if "mcp_server_ids" in fields and fields["mcp_server_ids"] is not None:
        fields["mcp_server_ids"] = [str(i) for i in fields["mcp_server_ids"]]
    if "tool_policy" in fields and fields["tool_policy"] is not None:
        # model_dump() leaves server_id as a UUID instance, which the JSON column's
        # serializer (json.dumps) cannot encode — must stringify before persisting.
        fields["tool_policy"] = [{**t, "server_id": str(t["server_id"])} for t in fields["tool_policy"]]

    agent = await service.update(agent, **fields)
    return _to_agent_out(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = AgentService(db)
    agent = await service.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    await service.delete(agent)


async def _load_agent_or_404(agent_id: uuid.UUID, db: AsyncSession):
    agent = await AgentService(db).get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.post("/{agent_id}/chat/stream")
async def agent_chat_stream(
    agent_id: uuid.UUID,
    req: ChatRequest,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent_or_404(agent_id, db)
    conv_service = ConversationService(db)
    conv = await conv_service.get_or_create(
        conversation_id=req.conversation_id,
        user_id=user.user_id,
        agent_id=agent.id,
        mode="agent",
        channel="api",
        runtime_config={},
    )

    chat_service = ChatService(db)
    event_stream = chat_service.run_turn(
        conversation_id=conv.id,
        user_id=user.user_id,
        content_blocks=[b.model_dump() for b in req.content_blocks],
        agent=agent,
        mcp_server_ids=agent.mcp_server_ids,
        knowledge_base_ids=agent.knowledge_base_ids,
    )
    return StreamingResponse(to_sse(event_stream, conversation_id=str(conv.id)), media_type="text/event-stream")


@router.post("/{agent_id}/chat/complete", response_model=ChatCompleteResponse)
async def agent_chat_complete(
    agent_id: uuid.UUID,
    req: ChatRequest,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent_or_404(agent_id, db)
    conv_service = ConversationService(db)
    conv = await conv_service.get_or_create(
        conversation_id=req.conversation_id,
        user_id=user.user_id,
        agent_id=agent.id,
        mode="agent",
        channel="api",
        runtime_config={},
    )

    chat_service = ChatService(db)
    event_stream = chat_service.run_turn(
        conversation_id=conv.id,
        user_id=user.user_id,
        content_blocks=[b.model_dump() for b in req.content_blocks],
        agent=agent,
        mcp_server_ids=agent.mcp_server_ids,
        knowledge_base_ids=agent.knowledge_base_ids,
    )
    async for _ in event_stream:
        pass

    history = await conv_service.get_history(conv.id, limit=1)
    last = history[-1] if history else None
    return ChatCompleteResponse(conversation_id=conv.id, content_blocks=last.content_blocks if last else [])
