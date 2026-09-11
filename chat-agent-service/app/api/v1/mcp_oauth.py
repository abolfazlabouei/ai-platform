"""
OAuth endpoints for per-user MCP server connections.

Endpoints:
  GET    /mcp-servers/{id}/oauth/authorize  - Generate OAuth consent URL (requires auth)
  GET    /mcp-servers/{id}/oauth/callback   - Public OAuth callback from Google
  GET    /mcp-servers/{id}/my-connection    - Check current user's connection status (requires auth)
  DELETE /mcp-servers/{id}/my-connection    - Disconnect current user's connection (requires auth)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.models.mcp_user_connection import OAuthConnectionStatus
from app.repositories.mcp_repo import McpRepo
from app.repositories.mcp_user_connection_repo import McpUserConnectionRepo
from app.schemas.mcp import McpAuthorizeOut, McpConnectionStatusOut
from app.services.oauth_service import OAuthService

router = APIRouter(prefix="/mcp-servers", tags=["mcp-oauth"])

_DEFAULT_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Connected successfully</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; padding-top: 80px;">
  <h2 style="color: #1a73e8;">Connected successfully</h2>
  <p style="color: #5f6368;">You can close this window and return to the application.</p>
</body>
</html>"""


@router.get("/{server_id}/oauth/authorize", response_model=McpAuthorizeOut)
async def authorize_mcp_server(
    server_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    mcp_repo = McpRepo(db)
    server = await mcp_repo.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if server.auth_config.get("type") != "oauth2_per_user":
        raise HTTPException(status_code=404, detail="MCP server does not use per-user OAuth2")

    service = OAuthService(db)
    try:
        url = service.build_authorization_url(server, user.user_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return McpAuthorizeOut(authorization_url=url)


@router.get("/{server_id}/oauth/callback")
async def oauth_callback(
    server_id: uuid.UUID,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth authorization error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing required code or state parameter")

    service = OAuthService(db)
    try:
        await service.handle_callback(server_id, code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {exc}")

    if settings.OAUTH_SUCCESS_REDIRECT_URL:
        return RedirectResponse(url=settings.OAUTH_SUCCESS_REDIRECT_URL, status_code=302)

    return HTMLResponse(content=_DEFAULT_SUCCESS_HTML)


@router.get("/{server_id}/my-connection", response_model=McpConnectionStatusOut)
async def get_my_connection(
    server_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    repo = McpUserConnectionRepo(db)
    conn = await repo.get(server_id, user.user_id)
    if not conn:
        return McpConnectionStatusOut(
            connected=False,
            status=OAuthConnectionStatus.DISCONNECTED.value,
            expires_at=None,
            scopes=None,
            last_error=None,
        )

    return McpConnectionStatusOut(
        connected=(conn.status == OAuthConnectionStatus.CONNECTED),
        status=conn.status.value,
        expires_at=conn.expires_at,
        scopes=conn.scopes,
        last_error=conn.last_error,
    )


@router.delete("/{server_id}/my-connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_my_connection(
    server_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    repo = McpUserConnectionRepo(db)
    conn = await repo.get(server_id, user.user_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    await repo.delete(conn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
