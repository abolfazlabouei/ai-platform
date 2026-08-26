"""
MCP server CRUD + test-connection (discovers & caches tools) + per-tool approve/reject
(with requires_hitl flag) that the graph's hitl_gate node consults at runtime.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.models.mcp_server import ToolApprovalStatus
from app.schemas.mcp import McpServerCreate, McpServerOut, McpToolOut, ToolApprovalUpdate
from app.services.mcp_service import McpService

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


def _to_server_out(s) -> McpServerOut:
    return McpServerOut(
        id=s.id,
        name=s.name,
        transport=s.transport.value,
        url=s.url,
        status=s.status.value,
        last_error=s.last_error,
        last_tested_at=s.last_tested_at,
        created_at=s.created_at,
    )


def _to_tool_out(t) -> McpToolOut:
    return McpToolOut(
        id=t.id,
        tool_name=t.tool_name,
        description=t.description,
        input_schema=t.input_schema,
        approval_status=t.approval_status.value,
        requires_hitl=t.requires_hitl,
    )


@router.post("", response_model=McpServerOut)
async def create_server(
    body: McpServerCreate, user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    service = McpService(db)
    server = await service.create_server(
        user_id=user.user_id, name=body.name, transport=body.transport, url=body.url, auth_config=body.auth_config
    )
    return _to_server_out(server)


@router.get("", response_model=list[McpServerOut])
async def list_servers(user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    service = McpService(db)
    return [_to_server_out(s) for s in await service.list_servers(user.user_id)]


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = McpService(db)
    server = await service.repo.get_server(server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    await service.delete_server(server)


@router.post("/{server_id}/test-connection", response_model=list[McpToolOut])
async def test_connection(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Connects to the server, discovers its tools, and caches them (approval_status=pending)."""
    service = McpService(db)
    server = await service.repo.get_server(server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")

    server = await service.test_connection(server)
    if server.status.value == "error":
        raise HTTPException(502, f"Could not connect to MCP server: {server.last_error}")

    tools = await service.list_tools(server_id)
    return [_to_tool_out(t) for t in tools]


@router.get("/{server_id}/tools", response_model=list[McpToolOut])
async def list_tools(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = McpService(db)
    return [_to_tool_out(t) for t in await service.list_tools(server_id)]


@router.patch("/{server_id}/tools/{tool_id}", response_model=McpToolOut)
async def set_tool_approval(
    server_id: uuid.UUID, tool_id: uuid.UUID, body: ToolApprovalUpdate, db: AsyncSession = Depends(get_db)
):
    """Approve or reject a discovered tool, and flag whether it requires human-in-the-loop
    confirmation before execution during chat."""
    service = McpService(db)
    tool = await service.repo.get_tool(tool_id)
    if not tool or tool.mcp_server_id != server_id:
        raise HTTPException(404, "Tool not found for this server")

    status = ToolApprovalStatus(body.approval_status)
    tool = await service.set_tool_approval(tool, status, body.requires_hitl)
    return _to_tool_out(tool)
