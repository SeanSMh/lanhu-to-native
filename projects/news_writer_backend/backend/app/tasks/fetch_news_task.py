"""新闻抓取任务（供 scheduler 调用 + CLI 手动触发）。

CLI 使用：
    uv run python -m app.tasks.fetch_news_task --once
"""

from __future__ import annotations

import argparse
import asyncio

from app.core.distributed_lock import try_lock
from app.core.logging import configure_logging, get_logger
from app.db.base import SessionLocal
from app.services.news_ingestion_service import fetch_and_store
from app.services.seed_service import seed_news_sources

logger = get_logger("task.fetch_news")

LOCK_KEY = "news_writer:lock:fetch_news"
# 比调度间隔（20 min）短一截；崩溃时 TTL 自动释放，不会长期阻塞。
LOCK_TTL_S = 900


async def run_once(categories: list[str] | None = None) -> dict:
    """抓取一轮。全局互斥：已有任务在跑时直接返回 skipped。"""
    async with try_lock(LOCK_KEY, ttl_s=LOCK_TTL_S) as got:
        if not got:
            logger.info("fetch_news_skipped_busy")
            return {"skipped": True, "reason": "busy"}
        async with SessionLocal() as session:
            await seed_news_sources(session)
        async with SessionLocal() as session:
            result = await fetch_and_store(session, categories=categories)
        logger.info("fetch_news_once_done", **result)
        return result


async def _main(categories: list[str] | None = None) -> None:
    await run_once(categories=categories)


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="运行一次后退出（否则由 scheduler 调度）")
    parser.add_argument("--category", action="append", help="仅抓取该 category，可多次")
    args = parser.parse_args()
    asyncio.run(_main(args.category or None))
