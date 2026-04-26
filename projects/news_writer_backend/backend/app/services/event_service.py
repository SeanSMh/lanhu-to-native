"""Events API service。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EventNotFound
from app.models.event import Event
from app.models.event_news_item import EventNewsItem
from app.models.image_asset import ImageAsset
from app.models.news_item import NewsItem
from app.models.news_source import NewsSource
from app.schemas.event import (
    CoverImage,
    EventDetail,
    EventListItem,
    EventNewsItem as EventNewsItemSchema,
    SuggestedAngle,
    TimelinePoint,
)
from app.utils.cursor import decode_cursor, encode_cursor


def _event_to_list_item(evt: Event) -> EventListItem:
    angle_label: str | None = None
    angles = evt.suggested_angles_json or []
    if angles:
        angle_label = angles[0].get("label") or angles[0].get("one_liner")
    return EventListItem(
        id=evt.id,
        title=evt.title,
        summary=evt.summary,
        category=evt.category,
        heat_score=evt.heat_score or 0.0,
        source_count=evt.source_count or 0,
        updated_at=evt.updated_at,
        suggested_angle=angle_label,
    )


async def list_events(
    session: AsyncSession,
    *,
    category: str | None = None,
    keyword: str | None = None,
    sort: Literal["heat", "latest"] = "heat",
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[EventListItem], str | None]:
    limit = max(1, min(limit, 50))
    q = select(Event).where(Event.status == "active")
    if category:
        q = q.where(Event.category == category)
    if keyword:
        pat = f"%{keyword}%"
        q = q.where(or_(Event.title.ilike(pat), Event.summary.ilike(pat)))

    cursor_data = decode_cursor(cursor)
    if sort == "latest":
        if cursor_data:
            c_ts = datetime.fromisoformat(cursor_data["updated_at"])
            c_id = cursor_data["id"]
            q = q.where(
                or_(
                    Event.updated_at < c_ts,
                    and_(Event.updated_at == c_ts, Event.id < c_id),
                )
            )
        q = q.order_by(Event.updated_at.desc(), Event.id.desc())
    else:  # heat
        if cursor_data:
            c_score = cursor_data["heat_score"]
            c_id = cursor_data["id"]
            q = q.where(
                or_(
                    Event.heat_score < c_score,
                    and_(Event.heat_score == c_score, Event.id < c_id),
                )
            )
        q = q.order_by(Event.heat_score.desc(), Event.id.desc())

    rows = list((await session.execute(q.limit(limit + 1))).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        if sort == "latest":
            next_cursor = encode_cursor({"updated_at": last.updated_at.isoformat(), "id": last.id})
        else:
            next_cursor = encode_cursor({"heat_score": last.heat_score or 0.0, "id": last.id})
        rows = rows[:limit]
    return [_event_to_list_item(r) for r in rows], next_cursor


async def get_event_detail(session: AsyncSession, event_id: str) -> EventDetail:
    evt = (
        await session.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if evt is None or evt.status == "archived":
        raise EventNotFound("事件不存在或已归档", {"event_id": event_id})
    cover: CoverImage | None = None
    if evt.cover_image_id:
        img = (
            await session.execute(
                select(ImageAsset).where(ImageAsset.id == evt.cover_image_id)
            )
        ).scalar_one_or_none()
        if img is not None:
            cover = CoverImage(image_asset_id=img.id, thumb_url=img.thumb_url)
    return EventDetail(
        id=evt.id,
        title=evt.title,
        summary=evt.summary,
        category=evt.category,
        heat_score=evt.heat_score or 0.0,
        source_count=evt.source_count or 0,
        status=evt.status,
        created_at=evt.created_at,
        updated_at=evt.updated_at,
        timeline=[TimelinePoint(**t) for t in (evt.timeline_json or []) if isinstance(t, dict)],
        keywords=list(evt.keywords_json or []),
        suggested_angles=[
            SuggestedAngle(**a) for a in (evt.suggested_angles_json or []) if isinstance(a, dict)
        ],
        cover_image=cover,
        controversy_points=list(evt.controversy_points_json or []),
    )


async def list_news_of_event(
    session: AsyncSession,
    event_id: str,
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[EventNewsItemSchema], str | None]:
    limit = max(1, min(limit, 50))
    # 确认 event 存在
    evt = (await session.execute(select(Event.id).where(Event.id == event_id))).scalar_one_or_none()
    if evt is None:
        raise EventNotFound("事件不存在", {"event_id": event_id})

    q = (
        select(NewsItem, NewsSource.name)
        .join(EventNewsItem, EventNewsItem.news_item_id == NewsItem.id)
        .join(NewsSource, NewsSource.id == NewsItem.source_id, isouter=True)
        .where(EventNewsItem.event_id == event_id)
    )
    cursor_data = decode_cursor(cursor)
    if cursor_data:
        c_ts = cursor_data.get("published_at")
        c_id = cursor_data["id"]
        if c_ts is not None:
            c_dt = datetime.fromisoformat(c_ts)
            q = q.where(
                or_(
                    NewsItem.published_at < c_dt,
                    and_(NewsItem.published_at == c_dt, NewsItem.id < c_id),
                )
            )
        else:
            q = q.where(NewsItem.id < c_id)
    q = q.order_by(NewsItem.published_at.desc().nullslast(), NewsItem.id.desc()).limit(limit + 1)

    rows = (await session.execute(q)).all()
    items: list[EventNewsItemSchema] = []
    for news_item, source_name in rows[:limit]:
        items.append(
            EventNewsItemSchema(
                id=news_item.id,
                title=news_item.title,
                description=news_item.description,
                url=news_item.url,
                source_name=source_name,
                author=news_item.author,
                published_at=news_item.published_at,
                image_url=news_item.image_url,
            )
        )
    next_cursor: str | None = None
    if len(rows) > limit:
        last_item, _ = rows[limit - 1]
        next_cursor = encode_cursor(
            {
                "published_at": last_item.published_at.isoformat() if last_item.published_at else None,
                "id": last_item.id,
            }
        )
    return items, next_cursor


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
