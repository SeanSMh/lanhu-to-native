"""多 worker 的内存 cache 失效广播：基于 Redis pubsub。

PATCH /settings/model 触发 publish_invalidation("model_settings")：
    1. 本 worker 立即 _invalidate_local
    2. Redis 发 pubsub；其它 worker 的后台订阅任务收到后也 _invalidate_local
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger

try:
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

CHANNEL = "news_writer:cache:invalidate"
logger = get_logger("cache_bus")

_redis = None


async def _get_redis():
    global _redis
    if aioredis is None:
        return None
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _invalidate_local(key: str) -> None:
    if key == "model_settings":
        from app.providers.llm.router import invalidate_llm_router_cache

        invalidate_llm_router_cache()
    # 未来可扩展其它 key


async def publish_invalidation(key: str) -> None:
    _invalidate_local(key)
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.publish(CHANNEL, key)
    except Exception as e:  # pragma: no cover
        logger.warning("cache_bus_publish_failed", error=str(e))


async def run_subscriber() -> None:
    """每个 worker 启动时跑一个订阅循环。"""
    r = await _get_redis()
    if r is None:
        return
    try:
        pubsub = r.pubsub()
        await pubsub.subscribe(CHANNEL)
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                data = msg.get("data")
                if isinstance(data, str):
                    _invalidate_local(data)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # pragma: no cover
        logger.warning("cache_bus_subscriber_crashed", error=str(e))
