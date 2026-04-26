"""事件聚合任务入口（scheduler + CLI）。"""

from __future__ import annotations

import argparse
import asyncio

from app.core.distributed_lock import try_lock
from app.core.logging import configure_logging, get_logger
from app.db.base import SessionLocal
from app.services.event_aggregation_service import run_aggregation

logger = get_logger("task.aggregate")

LOCK_KEY = "news_writer:lock:aggregate_events"
# 聚合比抓取慢，留够余量；崩溃靠 TTL 自动释放。
LOCK_TTL_S = 1500


async def run_once() -> dict:
    """聚合一轮。全局互斥：已有任务在跑时直接返回 skipped。"""
    async with try_lock(LOCK_KEY, ttl_s=LOCK_TTL_S) as got:
        if not got:
            logger.info("aggregate_events_skipped_busy")
            return {"skipped": True, "reason": "busy"}
        async with SessionLocal() as session:
            return await run_aggregation(session)


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_once())
