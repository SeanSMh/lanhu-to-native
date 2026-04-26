"""Auth service：登录 & 首启动种子。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.logging import get_logger
from app.core.security import hash_token
from app.models.user import User

logger = get_logger("auth")

INITIAL_USER_EMAIL = "self@news-writer.local"
INITIAL_USER_NICKNAME = "我"


async def login(session: AsyncSession, api_token: str) -> User:
    token_hash = hash_token(api_token)
    user = (
        await session.execute(select(User).where(User.api_token_hash == token_hash))
    ).scalar_one_or_none()
    if user is None:
        raise Unauthorized("token 不匹配")
    return user


async def ensure_initial_user(session: AsyncSession) -> User | None:
    """若 users 表为空，创建一个默认用户。"""
    any_user = (await session.execute(select(User).limit(1))).scalar_one_or_none()
    if any_user is not None:
        return any_user
    if not settings.auth_initial_api_token:
        logger.warning("no_initial_api_token_configured")
        return None
    user = User(
        id=str(ULID()),
        email=INITIAL_USER_EMAIL,
        nickname=INITIAL_USER_NICKNAME,
        api_token_hash=hash_token(settings.auth_initial_api_token),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info(
        "initial_user_created",
        user_id=user.id,
        email=user.email,
        note="api token 来自 AUTH_INITIAL_API_TOKEN（未打印原文）",
    )
    return user
