"""
auth_service: local username/password authentication. Issues the same JWT
format (sub = username, signed with settings.JWT_SECRET) that
app.core.security.require_user already verifies — no change needed there.
"""
from __future__ import annotations

import time

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.passwords import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repo import UserRepo

TOKEN_EXPIRES_HOURS = 24 * 7  # 7 days — adjust as needed


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def register(db: AsyncSession, username: str, password: str) -> User:
    repo = UserRepo(db)
    if await repo.get_by_username(username):
        raise UsernameTakenError(f"Username '{username}' is already taken")
    return await repo.create(username=username, password_hash=hash_password(password))


async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    repo = UserRepo(db)
    user = await repo.get_by_username(username)
    if not user or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid username or password")
    return user


def issue_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.username, "iat": now, "exp": now + TOKEN_EXPIRES_HOURS * 3600}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)