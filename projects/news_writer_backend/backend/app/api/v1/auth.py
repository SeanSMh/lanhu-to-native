"""Auth API：POST /auth/login & GET /auth/me。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import AuthResponse, LoginRequest, UserOut
from app.services.auth_service import login as do_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
async def login_endpoint(payload: LoginRequest, session: DbSession) -> AuthResponse:
    user = await do_login(session, payload.api_token)
    return AuthResponse(user=UserOut.model_validate(user))


@router.get("/me", response_model=AuthResponse)
async def me(user: CurrentUser) -> AuthResponse:
    return AuthResponse(user=UserOut.model_validate(user))
