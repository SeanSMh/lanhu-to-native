"""news_ingestion_service 测试：主要覆盖去重 & hash 计算。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.providers.news.base import NewsItemDraft
from app.services.news_ingestion_service import _already_stored, _content_hash, fetch_and_store
from app.models.news_item import NewsItem
from app.models.news_source import NewsSource as NewsSourceModel
from ulid import ULID

from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio]


def test_content_hash_stable():
    dt = datetime(2026, 4, 23, 11, 30, tzinfo=timezone.utc)
    a = _content_hash("Hello World", dt)
    b = _content_hash("  hello   world  ", dt.replace(minute=59))
    assert a == b  # 同小时 + 归一化后应一致


def test_content_hash_differs_by_hour():
    dt1 = datetime(2026, 4, 23, 11, 30, tzinfo=timezone.utc)
    dt2 = datetime(2026, 4, 23, 12, 30, tzinfo=timezone.utc)
    assert _content_hash("a", dt1) != _content_hash("a", dt2)


@skip_if_no_db
async def test_already_stored_by_url(session):
    existing = NewsItem(
        id=str(ULID()),
        source_id=None,
        title="t",
        url="https://e.com/1",
        content_hash=_content_hash("t", None),
    )
    session.add(existing)
    await session.commit()
    draft = NewsItemDraft(title="X different", url="https://e.com/1")
    assert await _already_stored(session, draft) is True


@skip_if_no_db
async def test_fetch_and_store_no_enabled_sources(session):
    stats = await fetch_and_store(session)
    assert stats == {"sources": 0, "fetched": 0, "inserted": 0, "failed_sources": 0}


@skip_if_no_db
async def test_fetch_and_store_raises_when_all_fail(session):
    # 加一个一定失败的源
    src = NewsSourceModel(
        id=str(ULID()),
        name="bad",
        type="rss",
        base_url="http://127.0.0.1:1/definitely-nothing",
        category="tech",
        is_enabled=True,
    )
    session.add(src)
    await session.commit()
    from app.core.errors import NewsSourceFailed

    with pytest.raises(NewsSourceFailed):
        await fetch_and_store(session)
