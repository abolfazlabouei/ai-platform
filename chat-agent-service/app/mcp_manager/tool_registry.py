"""
tool_registry: pure helper functions over the McpTool table — resolves which tools
are approved for a given set of MCP servers, and builds the {tool_name: requires_hitl}
map that hitl_gate uses. Kept separate from client_pool.py (which owns live
connections) so this module has no I/O beyond the DB.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_server import McpTool, ToolApprovalStatus


async def get_approved_tools(db: AsyncSession, mcp_server_ids: list[str]) -> list[McpTool]:
    if not mcp_server_ids:
        return []
    result = await db.execute(
        select(McpTool).where(
            McpTool.mcp_server_id.in_(mcp_server_ids),
            McpTool.approval_status == ToolApprovalStatus.APPROVED,
        )
    )
    return list(result.scalars().all())


def build_hitl_map(tools: list[McpTool]) -> dict[str, bool]:
    return {t.tool_name: t.requires_hitl for t in tools}
