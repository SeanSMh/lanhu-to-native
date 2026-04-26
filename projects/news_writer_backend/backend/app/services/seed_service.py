"""种子数据 service：默认 RSS 源 / 默认 style_profile。"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.logging import get_logger
from app.models.news_source import NewsSource as NewsSourceModel
from app.models.style_profile import StyleProfile
from app.models.user import User

logger = get_logger("seed")

DATA_DIR = Path(__file__).parent.parent / "data"


async def seed_news_sources(session: AsyncSession) -> int:
    """news_sources 表为空时，从 seed_rss_sources.json 批量插入。"""
    existing = (await session.execute(select(NewsSourceModel.id).limit(1))).scalar_one_or_none()
    if existing is not None:
        return 0
    path = DATA_DIR / "seed_rss_sources.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for row in raw:
        session.add(
            NewsSourceModel(
                id=str(ULID()),
                name=row["name"],
                type=row["type"],
                base_url=row["base_url"],
                category=row["category"],
                is_enabled=True,
                config_json={},
            )
        )
        count += 1
    await session.commit()
    logger.info("seed_news_sources_done", inserted=count)
    return count


async def seed_default_style_profile(session: AsyncSession) -> StyleProfile | None:
    """为已有用户生成默认 style_profile。"""
    user = (await session.execute(select(User).limit(1))).scalar_one_or_none()
    if user is None:
        return None
    existing = (
        await session.execute(
            select(StyleProfile).where(
                StyleProfile.user_id == user.id, StyleProfile.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    profile = StyleProfile(
        id=str(ULID()),
        user_id=user.id,
        name="默认风格",
        tone="理性、克制、有判断",
        forbidden_words_json=["震惊", "必看", "彻底爆了"],
        preferred_structure="先结论后展开",
        paragraph_style="短段落，每段 2-4 句",
        headline_style="疑问句或判断句，避免感叹号",
        prompt_preset=None,
        is_default=True,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    logger.info("seed_default_style_profile_done", profile_id=profile.id)
    return profile
