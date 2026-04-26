"""APScheduler 调度入口：由 lifespan 启动，进程退出时关闭。"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger

logger = get_logger("scheduler")


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    """创建并启动调度器。重复调用返回同一实例。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone="UTC")

    # Step 6：20 分钟抓一次新闻
    from app.tasks.fetch_news_task import run_once as fetch_news_once

    async def _fetch_news_job():
        try:
            await fetch_news_once()
        except Exception as e:  # pragma: no cover
            logger.warning("fetch_news_job_error", error=str(e))

    sched.add_job(
        _fetch_news_job,
        "interval",
        minutes=20,
        id="fetch_news",
        max_instances=1,
        coalesce=True,
    )

    # Step 7：30 分钟聚合事件
    from app.tasks.aggregate_events_task import run_once as aggregate_once

    async def _aggregate_job():
        try:
            await aggregate_once()
        except Exception as e:  # pragma: no cover
            logger.warning("aggregate_events_job_error", error=str(e))

    sched.add_job(
        _aggregate_job,
        "interval",
        minutes=30,
        id="aggregate_events",
        max_instances=1,
        coalesce=True,
    )

    sched.start()
    _scheduler = sched
    logger.info("scheduler_started")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")
