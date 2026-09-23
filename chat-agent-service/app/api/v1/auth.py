"""
Auth endpoints. /register and /login are public (no bearer token required);
/me and /logout require an existing valid token.

⚠️ /register is currently public — anyone who can reach this API can create
an account. If that's not desired (e.g. staff-only system), restrict it later
(admin-only creation, invite codes, etc.) — flagging this now since it wasn't
explicitly decided.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, require_user
from app.db.session import get_db
from app.repositories.user_repo import UserRepo
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.register(db, body.username, body.password)
    except auth_service.UsernameTakenError as exc:
        raise HTTPException(409, str(exc)) from exc
    return UserOut(id=user.id, username=user.username, created_at=user.created_at)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.authenticate(db, body.username, body.password)
    except auth_service.InvalidCredentialsError as exc:
        raise HTTPException(401, str(exc)) from exc

    token = auth_service.issue_token(user)
    return LoginResponse(
        access_token=token,
        user=UserOut(id=user.id, username=user.username, created_at=user.created_at),
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    repo = UserRepo(db)
    db_user = await repo.get_by_username(user.user_id)
    if not db_user:
        raise HTTPException(404, "User not found")
    return UserOut(id=db_user.id, username=db_user.username, created_at=db_user.created_at)


@router.post("/logout")
async def logout(user: CurrentUser = Depends(require_user)):
    # JWTs here are stateless — there's nothing server-side to invalidate.
    # This endpoint exists purely so the frontend has something to call.
    return {"status": "ok"}