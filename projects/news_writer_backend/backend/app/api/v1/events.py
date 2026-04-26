"""/api/v1/events/* — 4 个接口。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, status
from ulid import ULID

from app.api.deps import CurrentUser, DbSession
from app.core.logging import get_logger
from app.schemas.event import (
    EventDetail,
    EventListResponse,
    EventNewsListResponse,
    EventsRefreshRequest,
    EventsRefreshResponse,
)
from app.services.event_service import (
    get_event_detail,
    list_events,
    list_news_of_event,
    now_utc,
)

router = APIRouter(prefix="/events", tags=["events"])
logger = get_logger("events_api")


@router.get("", response_model=EventListResponse)
async def list_events_endpoint(
    user: CurrentUser,
    session: DbSession,
    category: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    sort: str = Query(default="heat", pattern="^(heat|latest)$"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> EventListResponse:
    items, next_cursor = await list_events(
        session,
        category=category,
        keyword=keyword,
        sort=sort,  # type: ignore[arg-type]
        cursor=cursor,
        limit=limit,
    )
    return EventListResponse(items=items, next_cursor=next_cursor)


@router.get("/{event_id}", response_model=EventDetail)
async def event_detail_endpoint(
    event_id: str, user: CurrentUser, session: DbSession
) -> EventDetail:
    return await get_event_detail(session, event_id)


@router.get("/{event_id}/news", response_model=EventNewsListResponse)
async def event_news_endpoint(
    event_id: str,
    user: CurrentUser,
    session: DbSession,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> EventNewsListResponse:
    items, next_cursor = await list_news_of_event(
        session, event_id, cursor=cursor, limit=limit
    )
    return EventNewsListResponse(items=items, next_cursor=next_cursor)


@router.post(
    "/refresh",
    response_model=EventsRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_endpoint(
    payload: EventsRefreshRequest,
    user: CurrentUser,
) -> EventsRefreshResponse:
    """后台异步触发：先抓新闻，再做聚合。立即返回 job_id。

    幂等语义：`fetch_news_task.run_once` 和 `aggregate_events_task.run_once`
    都以 Redis 分布式锁互斥，若已有任务在跑（定时器或上一次 refresh），
    本次会被安静 skip，不会放大上游 RSS/LLM 调用量。
    """
    job_id = str(ULID())

    async def _run():
        # 走带锁的 run_once，在所有 worker 之间互斥
        from app.tasks.aggregate_events_task import run_once as aggregate_once
        from app.tasks.fetch_news_task import run_once as fetch_once

        try:
            await fetch_once(categories=payload.categories)
        except Exception as e:  # 不阻断聚合尝试
            logger.warning("refresh_fetch_failed", job_id=job_id, error=str(e)[:200])
        try:
            await aggregate_once()
        except Exception as e:
            logger.warning("refresh_aggregate_failed", job_id=job_id, error=str(e)[:200])

    asyncio.create_task(_run())
    return EventsRefreshResponse(job_id=job_id, accepted_at=now_utc())
