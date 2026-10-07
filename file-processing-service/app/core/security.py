"""
Auth dependency shared by all v1 routers.

TEMPORARY (local/demo mode): when settings.AUTH_DISABLED is true (the default
right now), no bearer token is required. If a valid token IS sent, its `sub` is
still used as user_id (so existing per-user data keeps working); otherwise every
request is treated as settings.AUTH_DISABLED_USER_ID. Set AUTH_DISABLED=false to
restore strict JWT verification — nothing else in the codebase needs to change.
"""
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


def _decode(token: str) -> dict:
    options = {"verify_aud": settings.JWT_AUDIENCE is not None}
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        options=options,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if settings.AUTH_DISABLED:
        if credentials is not None:
            try:
                claims = _decode(credentials.credentials)
                user_id = claims.get("sub") or claims.get("user_id")
                if user_id:
                    return CurrentUser(user_id=str(user_id), raw_claims=claims)
            except jwt.PyJWTError:
                pass  # auth disabled: an invalid token is simply ignored
        return CurrentUser(user_id=settings.AUTH_DISABLED_USER_ID, raw_claims={})

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        claims = _decode(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc

    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")
    return CurrentUser(user_id=str(user_id), raw_claims=claims)


# Convenience alias used across routers: `user: CurrentUser = Depends(require_user)`
require_user = get_current_user
