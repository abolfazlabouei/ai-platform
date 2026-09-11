from datetime import datetime, timedelta, timezone
import time
import uuid
import pytest
import jwt
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.fernet import Fernet

from app.core import encryption
from app.core.config import settings
from app.models.mcp_server import McpServer, McpTransport
from app.models.mcp_user_connection import McpUserConnection, OAuthConnectionStatus
from app.services.oauth_service import OAuthService


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret-key-at-least-32-bytes-long!")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_REDIRECT_BASE_URL", "http://localhost:8101")
    encryption._fernet.cache_clear()
    yield
    encryption._fernet.cache_clear()


@pytest.fixture
def mock_server():
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


def test_build_authorization_url(mock_server):
    service = OAuthService()
    url = service.build_authorization_url(mock_server, "user_123")

    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url

    # Verify state JWT
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    state_token = query["state"][0]

    payload = jwt.decode(state_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["user_id"] == "user_123"
    assert payload["mcp_server_id"] == str(mock_server.id)


def test_build_authorization_url_invalid_server_type():
    server = MagicMock(spec=McpServer)
    server.id = uuid.uuid4()
    server.auth_config = {"type": "bearer", "token": "abc"}

    service = OAuthService()
    with pytest.raises(ValueError, match="does not use oauth2_per_user auth"):
        service.build_authorization_url(server, "user_123")


def test_state_csrf_verification(mock_server):
    service = OAuthService()

    # 1. Tampered state rejected
    now = int(time.time())
    valid_payload = {"mcp_server_id": str(mock_server.id), "user_id": "user_1", "exp": now + 600, "iat": now}
    tampered_state = jwt.encode(valid_payload, "wrong-secret-key-that-is-at-least-32-bytes-long!", algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid or expired state parameter"):
        service.verify_state(tampered_state, mock_server.id)

    # 2. Expired state rejected
    expired_payload = {"mcp_server_id": str(mock_server.id), "user_id": "user_1", "exp": now - 10, "iat": now - 600}
    expired_state = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(ValueError, match="Invalid or expired state parameter"):
        service.verify_state(expired_state, mock_server.id)

    # 3. Mismatched server_id rejected
    different_server_id = uuid.uuid4()
    valid_state = jwt.encode(valid_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(ValueError, match="State mcp_server_id does not match"):
        service.verify_state(valid_state, different_server_id)


@pytest.mark.asyncio
async def test_handle_callback_success(mock_server):
    mock_db = AsyncMock()
    service = OAuthService(mock_db)

    now = int(time.time())
    state_payload = {"mcp_server_id": str(mock_server.id), "user_id": "user_123", "exp": now + 600, "iat": now}
    state = jwt.encode(state_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "access_token": "ya29.new_access_token",
        "refresh_token": "1//new_refresh_token",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/calendar",
    }

    mock_connection = MagicMock(spec=McpUserConnection)
    mock_connection.status = OAuthConnectionStatus.CONNECTED
    service.repo.upsert = AsyncMock(return_value=mock_connection)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_resp
        conn = await service.handle_callback(mock_server.id, code="test-code", state=state)

    assert conn.status == OAuthConnectionStatus.CONNECTED
    service.repo.upsert.assert_awaited_once()
    _, kwargs = service.repo.upsert.call_args
    assert kwargs["user_id"] == "user_123"
    assert kwargs["mcp_server_id"] == mock_server.id
    # Ensure tokens were encrypted before storing
    assert encryption.decrypt_str(kwargs["access_token_encrypted"]) == "ya29.new_access_token"
    assert encryption.decrypt_str(kwargs["refresh_token_encrypted"]) == "1//new_refresh_token"


@pytest.mark.asyncio
async def test_get_valid_access_token_returns_none_when_no_connection(mock_server):
    mock_db = AsyncMock()
    service = OAuthService(mock_db)
    service.repo.get = AsyncMock(return_value=None)

    token = await service.get_valid_access_token(mock_server.id, "user_123")
    assert token is None


@pytest.mark.asyncio
async def test_get_valid_access_token_valid_unexpired(mock_server):
    mock_db = AsyncMock()
    service = OAuthService(mock_db)

    conn = McpUserConnection(
        id=uuid.uuid4(),
        mcp_server_id=mock_server.id,
        user_id="user_123",
        access_token_encrypted=encryption.encrypt_str("valid_token_abc"),
        refresh_token_encrypted=encryption.encrypt_str("refresh_token_xyz"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=OAuthConnectionStatus.CONNECTED,
    )
    service.repo.get = AsyncMock(return_value=conn)

    token = await service.get_valid_access_token(mock_server.id, "user_123")
    assert token == "valid_token_abc"


@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_when_expired(mock_server):
    mock_db = AsyncMock()
    service = OAuthService(mock_db)

    conn = McpUserConnection(
        id=uuid.uuid4(),
        mcp_server_id=mock_server.id,
        user_id="user_123",
        access_token_encrypted=encryption.encrypt_str("old_expired_token"),
        refresh_token_encrypted=encryption.encrypt_str("my_refresh_token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        status=OAuthConnectionStatus.CONNECTED,
    )
    service.repo.get = AsyncMock(return_value=conn)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "access_token": "ya29.refreshed_token",
        "expires_in": 3600,
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_resp
        token = await service.get_valid_access_token(mock_server.id, "user_123")

    assert token == "ya29.refreshed_token"
    assert conn.status == OAuthConnectionStatus.CONNECTED
    assert encryption.decrypt_str(conn.access_token_encrypted) == "ya29.refreshed_token"
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_get_valid_access_token_sets_expired_on_refresh_failure(mock_server):
    mock_db = AsyncMock()
    service = OAuthService(mock_db)

    conn = McpUserConnection(
        id=uuid.uuid4(),
        mcp_server_id=mock_server.id,
        user_id="user_123",
        access_token_encrypted=encryption.encrypt_str("old_token"),
        refresh_token_encrypted=encryption.encrypt_str("revoked_refresh_token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        status=OAuthConnectionStatus.CONNECTED,
    )
    service.repo.get = AsyncMock(return_value=conn)

    fake_resp = MagicMock()
    fake_resp.status_code = 400
    fake_resp.text = '{"error": "invalid_grant"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_resp
        token = await service.get_valid_access_token(mock_server.id, "user_123")

    assert token is None
    assert conn.status == OAuthConnectionStatus.EXPIRED
    assert "Token refresh failed" in conn.last_error
    mock_db.commit.assert_awaited()
