"""
Service-to-service auth.

Two layers, both required for MCP tool calls:
  1. X-Sandbox-Key: a shared secret proving the caller is a platform service
     (chat-agent-service). Checked on every REST and MCP request. The UI never
     talks to this service directly.
  2. X-Sandbox-Context: a short-lived HS256 JWT minted by chat-agent-service per
     conversation, carrying {conversation_id, user_id, exp}. This is the ONLY
     source of identity for MCP tools — ids are never accepted as tool arguments,
     so a prompt-injected model cannot target another user's session.
"""
from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings

KEY_HEADER = "x-sandbox-key"
CONTEXT_HEADER = "x-sandbox-context"
CONTEXT_MAX_LIFETIME_SECONDS = 5 * 60


class InvalidContext(Exception):
    """Missing, malformed, expired or wrongly-signed X-Sandbox-Context."""


@dataclass(frozen=True)
class SandboxContext:
    conversation_id: str
    user_id: str


def check_shared_key(presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(presented.encode(), settings.SANDBOX_SHARED_SECRET.encode())


async def require_service_key(x_sandbox_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency for every /api/v1 route."""
    if not check_shared_key(x_sandbox_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Sandbox-Key")


def decode_context(token: str | None) -> SandboxContext:
    if not token:
        raise InvalidContext("missing sandbox context")
    try:
        claims = jwt.decode(
            token,
            settings.SANDBOX_CONTEXT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "conversation_id", "user_id"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidContext(f"invalid sandbox context: {exc}") from exc
    # Reject long-lived tokens even if correctly signed.
    if int(claims["exp"]) - int(claims["iat"]) > CONTEXT_MAX_LIFETIME_SECONDS:
        raise InvalidContext("sandbox context lifetime too long")
    conversation_id = str(claims["conversation_id"]).strip()
    user_id = str(claims["user_id"]).strip()
    if not conversation_id or not user_id:
        raise InvalidContext("sandbox context missing ids")
    return SandboxContext(conversation_id=conversation_id, user_id=user_id)


def context_from_headers(headers: Mapping[str, str] | None) -> SandboxContext:
    """Validates both headers of an MCP request and returns the caller's identity."""
    if headers is None:
        raise InvalidContext("request carries no headers")
    lowered = {k.lower(): v for k, v in headers.items()}
    if not check_shared_key(lowered.get(KEY_HEADER)):
        raise InvalidContext("invalid or missing X-Sandbox-Key")
    return decode_context(lowered.get(CONTEXT_HEADER))
