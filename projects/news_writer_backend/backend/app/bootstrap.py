"""应用启动种子：默认用户、默认 style_profile、默认 RSS 源（幂等）。"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.services.auth_service import ensure_initial_user
from app.services.seed_service import seed_default_style_profile, seed_news_sources

logger = get_logger("bootstrap")


async def run_bootstrap() -> None:
    async with SessionLocal() as session:
        await ensure_initial_user(session)
    async with SessionLocal() as session:
        await seed_default_style_profile(session)
    async with SessionLocal() as session:
        await seed_news_sources(session)
