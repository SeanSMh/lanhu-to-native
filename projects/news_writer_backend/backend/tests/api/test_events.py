from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from ulid import ULID

from app.models.event import Event
from app.models.event_news_item import EventNewsItem
from app.models.news_item import NewsItem
from app.models.news_source import NewsSource
from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


async def _seed_event_with_news(session):
    src = NewsSource(
        id=str(ULID()),
        name="测试源",
        type="rss",
        base_url="https://example.com/feed",
        category="tech",
    )
    session.add(src)
    news = NewsItem(
        id=str(ULID()),
        source_id=src.id,
        title="测试新闻 A",
        url=f"https://example.com/{ULID()}",
        content_hash="hash-a",
        category="tech",
        published_at=datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc),
    )
    session.add(news)
    evt = Event(
        id=str(ULID()),
        title="测试事件",
        summary="一句话摘要",
        category="tech",
        heat_score=0.9,
        source_count=3,
        status="active",
        suggested_angles_json=[{"angle_type": "trend", "label": "趋势", "one_liner": "one"}],
        timeline_json=[{"time": "2026-04-23T08:00:00Z", "text": "A 媒体首发"}],
        keywords_json=["测试"],
    )
    session.add(evt)
    await session.flush()
    session.add(EventNewsItem(id=str(ULID()), event_id=evt.id, news_item_id=news.id))
    await session.commit()
    return evt, news, src


async def test_list_events_empty(client: AsyncClient, auth_header):
    r = await client.get("/api/v1/events", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


async def test_list_events_with_one(client: AsyncClient, auth_header, session):
    evt, _, _ = await _seed_event_with_news(session)
    r = await client.get("/api/v1/events", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == evt.id
    assert body["items"][0]["heat_score"] == 0.9


async def test_event_detail_ok(client: AsyncClient, auth_header, session):
    evt, _, _ = await _seed_event_with_news(session)
    r = await client.get(f"/api/v1/events/{evt.id}", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == evt.id
    assert body["suggested_angles"][0]["angle_type"] == "trend"


async def test_event_detail_404(client: AsyncClient, auth_header):
    r = await client.get("/api/v1/events/01HNOTEXIST00000000000000A", headers=auth_header)
    assert r.status_code == 404
    assert r.json()["code"] == "event_not_found"


async def test_event_news_list(client: AsyncClient, auth_header, session):
    evt, news, src = await _seed_event_with_news(session)
    r = await client.get(f"/api/v1/events/{evt.id}/news", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == news.id
    assert body["items"][0]["source_name"] == src.name


async def test_refresh_accepts(client: AsyncClient, auth_header, monkeypatch):
    # 避免真跑抓取：打桩两个服务
    from app.services import news_ingestion_service, event_aggregation_service

    async def fake_fetch(session, *, categories=None):
        return {"sources": 0, "fetched": 0, "inserted": 0, "failed_sources": 0}

    async def fake_aggregate(session):
        return {"items": 0, "new_events": 0, "grown_events": 0}

    monkeypatch.setattr(news_ingestion_service, "fetch_and_store", fake_fetch)
    monkeypatch.setattr(event_aggregation_service, "run_aggregation", fake_aggregate)

    r = await client.post("/api/v1/events/refresh", json={}, headers=auth_header)
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["accepted_at"].endswith("Z") or "+" in body["accepted_at"]
