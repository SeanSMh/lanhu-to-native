"""新闻抓取 & 去重 & 入库 service。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.errors import NewsSourceFailed
from app.core.logging import get_logger
from app.models.news_item import NewsItem
from app.models.news_source import NewsSource as NewsSourceModel
from app.providers.news.base import NewsItemDraft
from app.providers.news.rss_adapter import RSSNewsSource

logger = get_logger("news_ingestion")

FAILURE_DISABLE_THRESHOLD = 10


def _norm_title(title: str) -> str:
    return " ".join(title.split()).lower()


def _content_hash(title: str, published_at: datetime | None) -> str:
    hour_bucket = ""
    if published_at is not None:
        ts = published_at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hour_bucket = ts.isoformat()
    blob = f"{_norm_title(title)}|{hour_bucket}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build_source_adapter(row: NewsSourceModel):
    if row.type != "rss":
        return None
    return RSSNewsSource(name=row.name, base_url=row.base_url, category=row.category)


async def _upsert_source_health(session: AsyncSession, row: NewsSourceModel, ok: bool) -> None:
    if ok:
        row.consecutive_failures = 0
        row.last_fetched_at = datetime.now(timezone.utc)
    else:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        if row.consecutive_failures >= FAILURE_DISABLE_THRESHOLD:
            row.is_enabled = False
            logger.warning("news_source_auto_disabled", source=row.name, failures=row.consecutive_failures)


async def fetch_and_store(
    session: AsyncSession, *, categories: list[str] | None = None
) -> dict[str, int]:
    """从所有启用的源抓取、去重、入库。返回统计 dict。"""
    q = select(NewsSourceModel).where(NewsSourceModel.is_enabled.is_(True))
    if categories:
        q = q.where(NewsSourceModel.category.in_(categories))
    sources: list[NewsSourceModel] = list((await session.execute(q)).scalars().all())
    fetched = 0
    inserted = 0
    failed_sources = 0
    for src in sources:
        adapter = _build_source_adapter(src)
        if adapter is None:
            continue
        try:
            drafts = await adapter.fetch()
        except NewsSourceFailed as e:
            failed_sources += 1
            logger.warning("news_source_failed", source=src.name, error=e.message)
            await _upsert_source_health(session, src, ok=False)
            await session.commit()
            continue
        await _upsert_source_health(session, src, ok=True)
        await session.commit()

        for draft in drafts:
            fetched += 1
            if await _already_stored(session, draft):
                continue
            item = NewsItem(
                id=str(ULID()),
                source_id=src.id,
                title=draft.title,
                description=draft.description,
                url=draft.url,
                author=draft.author,
                published_at=draft.published_at,
                image_url=draft.image_url,
                content_hash=_content_hash(draft.title, draft.published_at),
                raw_payload=draft.raw_payload or {},
                category=draft.category or src.category,
                language=draft.language,
            )
            session.add(item)
            try:
                await session.commit()
                inserted += 1
            except Exception:
                await session.rollback()

    logger.info(
        "news_ingestion_done",
        sources=len(sources),
        fetched=fetched,
        inserted=inserted,
        failed_sources=failed_sources,
    )
    if failed_sources == len(sources) and sources:
        raise NewsSourceFailed("所有新闻源都失败")
    return {
        "sources": len(sources),
        "fetched": fetched,
        "inserted": inserted,
        "failed_sources": failed_sources,
    }


async def _already_stored(session: AsyncSession, draft: NewsItemDraft) -> bool:
    # 1. URL 命中
    exists_by_url = (
        await session.execute(select(NewsItem.id).where(NewsItem.url == draft.url))
    ).scalar_one_or_none()
    if exists_by_url is not None:
        return True
    # 2. content_hash 命中
    ch = _content_hash(draft.title, draft.published_at)
    exists_by_hash = (
        await session.execute(select(NewsItem.id).where(NewsItem.content_hash == ch))
    ).scalar_one_or_none()
    return exists_by_hash is not None
