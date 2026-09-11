"""
OAuthService: handles Google OAuth2 flow for McpServer instances configured with
auth_config.type == "oauth2_per_user".

Responsibilities:
1. build_authorization_url: Generates Google OAuth consent URL with signed CSRF state.
2. handle_callback: Verifies state, exchanges auth code for tokens, encrypts and upserts connection.
3. refresh_token: Refreshes an expired access token using the stored refresh token.
4. get_valid_access_token: Single entrypoint to obtain a decrypted, valid access token.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import decrypt_str, encrypt_str
from app.models.mcp_server import McpServer
from app.models.mcp_user_connection import McpUserConnection, OAuthConnectionStatus
from app.repositories.mcp_user_connection_repo import McpUserConnectionRepo

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthService:
    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self.repo = McpUserConnectionRepo(db) if db is not None else None

    def build_authorization_url(self, server: McpServer, user_id: str) -> str:
        if server.auth_config.get("type") != "oauth2_per_user":
            raise ValueError(f"MCP server '{server.id}' does not use oauth2_per_user auth")

        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID is not configured in settings")

        redirect_uri = (
            f"{settings.GOOGLE_OAUTH_REDIRECT_BASE_URL.rstrip('/')}/api/v1/mcp-servers/{server.id}/oauth/callback"
        )

        scopes = server.auth_config.get("scopes", [])
        scope_str = " ".join(scopes) if isinstance(scopes, list) else str(scopes)

        now = int(time.time())
        state_payload = {
            "mcp_server_id": str(server.id),
            "user_id": user_id,
            "iat": now,
            "exp": now + 600,  # 10 minute expiration
        }
        state = jwt.encode(state_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope_str,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def verify_state(self, state: str, server_id: uuid.UUID) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                state,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": True},
            )
        except jwt.PyJWTError as exc:
            raise ValueError(f"Invalid or expired state parameter: {exc}") from exc

        if payload.get("mcp_server_id") != str(server_id):
            raise ValueError("State mcp_server_id does not match URL server_id")

        if not payload.get("user_id"):
            raise ValueError("State payload missing user_id")

        return payload

    async def handle_callback(self, server_id: uuid.UUID, code: str, state: str) -> McpUserConnection:
        if self.db is None or self.repo is None:
            raise RuntimeError("OAuthService must be initialized with an AsyncSession for handle_callback")

        payload = self.verify_state(state, server_id)
        user_id = str(payload["user_id"])

        redirect_uri = (
            f"{settings.GOOGLE_OAUTH_REDIRECT_BASE_URL.rstrip('/')}/api/v1/mcp-servers/{server_id}/oauth/callback"
        )

        data = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)

        if resp.status_code != 200:
            raise RuntimeError(f"Google token exchange failed ({resp.status_code}): {resp.text}")

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("Google token exchange response missing access_token")

        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        scope = token_data.get("scope")

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in is not None else None
        )

        access_token_encrypted = encrypt_str(access_token)
        refresh_token_encrypted = encrypt_str(refresh_token) if refresh_token else None

        if refresh_token_encrypted is None:
            existing = await self.repo.get(server_id, user_id)
            if existing and existing.refresh_token_encrypted:
                refresh_token_encrypted = existing.refresh_token_encrypted

        connection = await self.repo.upsert(
            mcp_server_id=server_id,
            user_id=user_id,
            access_token_encrypted=access_token_encrypted,
            refresh_token_encrypted=refresh_token_encrypted,
            expires_at=expires_at,
            scopes=scope,
            status=OAuthConnectionStatus.CONNECTED,
            last_error=None,
        )
        return connection

    async def refresh_token(self, connection: McpUserConnection) -> str | None:
        if self.db is None:
            raise RuntimeError("OAuthService must have an active session to refresh tokens")

        if not connection.refresh_token_encrypted:
            connection.status = OAuthConnectionStatus.EXPIRED
            connection.last_error = "No refresh token available"
            await self.db.commit()
            return None

        try:
            refresh_token = decrypt_str(connection.refresh_token_encrypted)
        except Exception as exc:
            connection.status = OAuthConnectionStatus.EXPIRED
            connection.last_error = f"Failed to decrypt refresh token: {exc}"
            await self.db.commit()
            return None

        data = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(GOOGLE_TOKEN_URL, data=data)

            if resp.status_code != 200:
                connection.status = OAuthConnectionStatus.EXPIRED
                connection.last_error = f"Token refresh failed ({resp.status_code}): {resp.text}"
                await self.db.commit()
                return None

            token_data = resp.json()
            new_access_token = token_data.get("access_token")
            if not new_access_token:
                connection.status = OAuthConnectionStatus.EXPIRED
                connection.last_error = "Token refresh response missing access_token"
                await self.db.commit()
                return None

            expires_in = token_data.get("expires_in")
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in is not None else None
            )

            connection.access_token_encrypted = encrypt_str(new_access_token)
            connection.expires_at = expires_at

            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                connection.refresh_token_encrypted = encrypt_str(new_refresh)

            connection.status = OAuthConnectionStatus.CONNECTED
            connection.last_error = None
            await self.db.commit()
            return new_access_token
        except Exception as exc:
            connection.status = OAuthConnectionStatus.EXPIRED
            connection.last_error = f"Exception during token refresh: {exc}"
            await self.db.commit()
            return None

    async def _get_valid_access_token_impl(
        self, session: AsyncSession, repo: McpUserConnectionRepo, mcp_server_id: uuid.UUID, user_id: str
    ) -> str | None:
        connection = await repo.get(mcp_server_id, user_id)
        if connection is None:
            return None
        if connection.status != OAuthConnectionStatus.CONNECTED:
            return None

        # Check if expired or within 60-second buffer
        now = datetime.now(timezone.utc)
        if connection.expires_at is not None and connection.expires_at <= (now + timedelta(seconds=60)):
            # Temporarily attach session if self.db differs
            old_db = self.db
            old_repo = self.repo
            self.db = session
            self.repo = repo
            try:
                return await self.refresh_token(connection)
            finally:
                self.db = old_db
                self.repo = old_repo

        try:
            return decrypt_str(connection.access_token_encrypted)
        except Exception:
            # If decrypting fails, attempt refresh
            old_db = self.db
            old_repo = self.repo
            self.db = session
            self.repo = repo
            try:
                return await self.refresh_token(connection)
            finally:
                self.db = old_db
                self.repo = old_repo

    async def get_valid_access_token(self, mcp_server_id: uuid.UUID, user_id: str) -> str | None:
        if self.db is not None and self.repo is not None:
            return await self._get_valid_access_token_impl(self.db, self.repo, mcp_server_id, user_id)
        else:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                repo = McpUserConnectionRepo(session)
                return await self._get_valid_access_token_impl(session, repo, mcp_server_id, user_id)


oauth_service = OAuthService()


async def get_valid_access_token(mcp_server_id: uuid.UUID, user_id: str) -> str | None:
    return await oauth_service.get_valid_access_token(mcp_server_id, user_id)
