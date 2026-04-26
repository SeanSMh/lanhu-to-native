"""FastAPI 依赖：session + current_user。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unauthorized
from app.core.security import hash_token
from app.db.base import get_session
from app.models.user import User


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized("缺少鉴权头")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise Unauthorized("token 为空")
    token_hash = hash_token(token)
    user = (
        await session.execute(select(User).where(User.api_token_hash == token_hash))
    ).scalar_one_or_none()
    if user is None:
        raise Unauthorized("token 无效")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
