from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch
import jwt

from fastapi import FastAPI
from app.api.v1.mcp_oauth import router
from app.core.config import settings
from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.models.mcp_server import McpServer, McpTransport
from app.models.mcp_user_connection import McpUserConnection, OAuthConnectionStatus

app = FastAPI()
app.include_router(router, prefix="/api/v1")


@pytest.fixture
def mock_user():
    return CurrentUser(user_id="user_test_456", raw_claims={"sub": "user_test_456"})


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def oauth_server():
    server = MagicMock(spec=McpServer)
    server.id = uuid.uuid4()
    server.name = "google-calendar"
    server.transport = McpTransport.SSE
    server.url = "http://localhost:8000/sse"
    server.auth_config = {
        "type": "oauth2_per_user",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    }
    return server


@pytest.mark.asyncio
async def test_authorize_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/mcp-servers/{uuid.uuid4()}/oauth/authorize")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_authorize_success(mock_user, mock_db_session, oauth_server):
    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    try:
        with (
            patch("app.repositories.mcp_repo.McpRepo.get_server", new_callable=AsyncMock) as mock_get_server,
            patch.object(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id"),
            patch.object(settings, "JWT_SECRET", "test-jwt-secret-key-at-least-32-bytes-long!"),
        ):
            mock_get_server.return_value = oauth_server

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/mcp-servers/{oauth_server.id}/oauth/authorize")

            assert resp.status_code == 200
            data = resp.json()
            assert "authorization_url" in data
            assert "accounts.google.com" in data["authorization_url"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_authorize_non_oauth_server_returns_404(mock_user, mock_db_session):
    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    server = MagicMock(spec=McpServer)
    server.id = uuid.uuid4()
    server.auth_config = {"type": "bearer", "token": "abc"}

    try:
        with patch("app.repositories.mcp_repo.McpRepo.get_server", new_callable=AsyncMock) as mock_get_server:
            mock_get_server.return_value = server

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/mcp-servers/{server.id}/oauth/authorize")

            assert resp.status_code == 404
            assert "does not use per-user OAuth2" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_callback_is_public_and_handles_success(mock_db_session, oauth_server):
    app.dependency_overrides[get_db] = lambda: mock_db_session

    mock_conn = MagicMock(spec=McpUserConnection)
    mock_conn.status = OAuthConnectionStatus.CONNECTED

    try:
        with patch("app.services.oauth_service.OAuthService.handle_callback", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = mock_conn

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # No Authorization header sent!
                resp = await client.get(
                    f"/api/v1/mcp-servers/{oauth_server.id}/oauth/callback?code=fake-code&state=fake-state"
                )

            assert resp.status_code == 200
            assert "Connected successfully" in resp.text
            mock_handle.assert_awaited_once_with(oauth_server.id, code="fake-code", state="fake-state")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_my_connection_unconnected(mock_user, mock_db_session, oauth_server):
    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    try:
        with patch("app.repositories.mcp_user_connection_repo.McpUserConnectionRepo.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/mcp-servers/{oauth_server.id}/my-connection")

            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is False
            assert data["status"] == "disconnected"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_my_connection_connected(mock_user, mock_db_session, oauth_server):
    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    conn = McpUserConnection(
        id=uuid.uuid4(),
        mcp_server_id=oauth_server.id,
        user_id=mock_user.user_id,
        access_token_encrypted="encrypted_tok",
        refresh_token_encrypted="encrypted_ref",
        expires_at=datetime.now(timezone.utc),
        scopes="https://www.googleapis.com/auth/calendar",
        status=OAuthConnectionStatus.CONNECTED,
    )

    try:
        with patch("app.repositories.mcp_user_connection_repo.McpUserConnectionRepo.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = conn

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/mcp-servers/{oauth_server.id}/my-connection")

            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is True
            assert data["status"] == "connected"
            assert data["scopes"] == "https://www.googleapis.com/auth/calendar"
            # Ensure tokens are NEVER returned
            assert "access_token" not in data
            assert "refresh_token" not in data
            assert "access_token_encrypted" not in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_my_connection(mock_user, mock_db_session, oauth_server):
    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db_session

    conn = MagicMock(spec=McpUserConnection)

    try:
        with (
            patch("app.repositories.mcp_user_connection_repo.McpUserConnectionRepo.get", new_callable=AsyncMock) as mock_get,
            patch("app.repositories.mcp_user_connection_repo.McpUserConnectionRepo.delete", new_callable=AsyncMock) as mock_delete,
        ):
            mock_get.return_value = conn

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete(f"/api/v1/mcp-servers/{oauth_server.id}/my-connection")

            assert resp.status_code == 204
            mock_delete.assert_awaited_once_with(conn)
    finally:
        app.dependency_overrides.clear()
