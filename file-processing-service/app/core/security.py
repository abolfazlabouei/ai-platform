"""JWT auth dependency — identical contract to chat-agent-service's, since both
trust tokens issued by the same upstream auth/gateway layer."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: str
    raw_claims: dict


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        options = {"verify_aud": settings.JWT_AUDIENCE is not None}
        claims = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc

    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")
    return CurrentUser(user_id=str(user_id), raw_claims=claims)


require_user = get_current_user
