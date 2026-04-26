"""事件聚合 service：embedding → 贪心聚类 → 更新/创建 event → 打热度分。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.logging import get_logger
from app.models.event import Event
from app.models.event_news_item import EventNewsItem
from app.models.news_item import NewsItem
from app.providers.embedding.router import get_embedding_provider
from app.services.llm_service import run_llm_job
from app.utils.clustering import cosine, greedy_cluster, update_centroid

logger = get_logger("event_aggregation")

SIMILARITY_THRESHOLD = 0.82
AGG_WINDOW_HOURS = 48
BATCH_EMBED = 32


async def _unclustered_recent(session: AsyncSession) -> list[NewsItem]:
    since = datetime.now(timezone.utc) - timedelta(hours=AGG_WINDOW_HOURS)
    sub = select(EventNewsItem.news_item_id)
    q = (
        select(NewsItem)
        .where(
            (NewsItem.published_at >= since) | (NewsItem.published_at.is_(None)),
            NewsItem.created_at >= since,
            ~NewsItem.id.in_(sub),
        )
        .order_by(NewsItem.published_at.desc().nullslast(), NewsItem.created_at.desc())
        .limit(400)
    )
    return list((await session.execute(q)).scalars().all())


async def _embed_items(items: list[NewsItem]) -> list[tuple[str, list[float]]]:
    if not items:
        return []
    provider = await get_embedding_provider()
    all_texts = [f"{i.title}\n{(i.description or '')[:500]}" for i in items]
    pairs: list[tuple[str, list[float]]] = []
    for start in range(0, len(all_texts), BATCH_EMBED):
        chunk = all_texts[start : start + BATCH_EMBED]
        vecs = await provider.embed(chunk)
        for item, vec in zip(items[start : start + BATCH_EMBED], vecs):
            item.embedding_json = vec
            item.embedded_at = datetime.now(timezone.utc)
            pairs.append((item.id, vec))
    return pairs


async def _active_events(session: AsyncSession) -> list[Event]:
    q = select(Event).where(
        Event.status == "active",
        Event.centroid_embedding.is_not(None),
    )
    return list((await session.execute(q)).scalars().all())


def _compute_heat_score(*, source_count: int, published_at: datetime | None,
                       keyword_weight: float, growth_hint: float) -> float:
    fresh_hours = 48.0
    if published_at is not None:
        delta = datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)
        fresh_hours = max(0.0, delta.total_seconds() / 3600.0)
    freshness = max(0.0, 1.0 - min(fresh_hours, 72.0) / 72.0)
    src = min(source_count / 10.0, 1.0)
    return round(0.35 * src + 0.35 * freshness + 0.2 * keyword_weight + 0.1 * growth_hint, 4)


async def _generate_event_summary(session: AsyncSession, items: list[NewsItem]) -> dict:
    items_sorted = sorted(
        items,
        key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    news_payload = [
        {
            "title": i.title,
            "description": (i.description or "")[:300],
            "source": i.source_id,
            "published_at": i.published_at.isoformat() if i.published_at else None,
            "url": i.url,
        }
        for i in items_sorted
    ]
    return await run_llm_job(
        session,
        job_type="event_summary",
        prompt_template_id="event_summary",
        variables={"count": len(news_payload), "news_json": news_payload},
    )


async def _attach_members(
    session: AsyncSession, event_id: str, member_ids: Iterable[str]
) -> None:
    for nid in member_ids:
        session.add(EventNewsItem(id=str(ULID()), event_id=event_id, news_item_id=nid))
    await session.commit()


async def run_aggregation(session: AsyncSession) -> dict:
    """跑一次聚合。返回统计 dict。"""
    items = await _unclustered_recent(session)
    if not items:
        logger.info("aggregation_no_items")
        return {"items": 0, "new_events": 0, "grown_events": 0}

    try:
        pairs = await _embed_items(items)
        await session.commit()  # 持久化 embedding_json
    except Exception as e:
        logger.warning("embedding_failed", error=str(e)[:200])
        await session.rollback()
        return {"items": len(items), "new_events": 0, "grown_events": 0, "error": "embedding_failed"}

    # 1. 先与现有 active events 匹配
    active_events = await _active_events(session)
    unmatched: list[tuple[str, list[float]]] = []
    grown = 0
    news_by_id = {i.id: i for i in items}
    for nid, vec in pairs:
        best: Event | None = None
        best_sim = -1.0
        for evt in active_events:
            sim = cosine(vec, evt.centroid_embedding or [])
            if sim > best_sim:
                best, best_sim = evt, sim
        if best is not None and best_sim >= SIMILARITY_THRESHOLD:
            # 加入该 event
            new_count = (best.source_count or 0) + 1
            best.centroid_embedding = update_centroid(best.centroid_embedding or [], vec, new_count)
            best.source_count = new_count
            await _attach_members(session, best.id, [nid])
            grown += 1
        else:
            unmatched.append((nid, vec))

    # 2. 对剩下的做贪心聚类；≥2 成员才建 event
    new_events = 0
    clusters = greedy_cluster(unmatched, threshold=SIMILARITY_THRESHOLD)
    for cluster in clusters:
        members = cluster["member_ids"]
        if len(members) < 2:
            continue
        member_items = [news_by_id[mid] for mid in members]
        try:
            summary = await _generate_event_summary(session, member_items)
        except Exception as e:
            logger.warning("event_summary_failed", error=str(e)[:200])
            continue
        primary = member_items[0]
        event_id = str(ULID())
        heat = _compute_heat_score(
            source_count=len(members),
            published_at=primary.published_at,
            keyword_weight=0.3,
            growth_hint=0.2,
        )
        session.add(
            Event(
                id=event_id,
                title=(summary.get("title") or primary.title)[:500],
                summary=(summary.get("summary") or None),
                timeline_json=summary.get("timeline") or [],
                keywords_json=summary.get("keywords") or [],
                suggested_angles_json=summary.get("suggested_angles") or [],
                controversy_points_json=summary.get("controversy_points") or [],
                category=primary.category,
                heat_score=heat,
                source_count=len(members),
                primary_news_id=primary.id,
                status="active",
                centroid_embedding=cluster["centroid"],
            )
        )
        await session.commit()
        await _attach_members(session, event_id, members)
        new_events += 1

    # 3. 刷新所有已变动事件的 heat_score（简单做法：对 grown 事件重算）
    for evt in active_events:
        evt.heat_score = _compute_heat_score(
            source_count=evt.source_count,
            published_at=evt.updated_at,
            keyword_weight=0.3,
            growth_hint=0.2,
        )
    await session.commit()

    logger.info(
        "aggregation_done",
        items=len(items),
        new_events=new_events,
        grown_events=grown,
    )
    return {"items": len(items), "new_events": new_events, "grown_events": grown}
