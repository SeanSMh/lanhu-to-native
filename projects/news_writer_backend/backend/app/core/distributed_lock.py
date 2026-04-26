"""跨进程/跨 worker 分布式锁（基于 Redis SETNX），带进程内兜底。

用法：

    async with try_lock("news_writer:lock:fetch_news", ttl_s=900) as got:
        if not got:
            logger.info("already_running")
            return
        ...  # 正常业务

语义：
- 多 worker 部署 + Redis 正常 → 由 Redis `SET NX EX` 保证全局互斥；TTL 到期自动释放。
- Redis 不可达（开发期未起 redis）→ 回落到进程内 asyncio.Lock，保证至少"单进程内互斥"。
- 锁未获得（被别人持有）→ yield False，调用方要自行决定 skip。
- 获得锁的一方退出 `async with` 时释放；异常路径也会释放（try/finally）。

安全性：
- 每次持有生成唯一 token；释放走 Lua EVAL 做 `if GET key == token then DEL`，
  避免"任务超 TTL → 锁被 Redis 自动释放 → 别人拿到 → 自己再 DEL 把别人的删了"的误删。
- 不解决"超 TTL 后自己仍在跑导致的并发执行窗口"——业务层对 LLM/去重本身具备幂等/去重
  能力（news_items.url UNIQUE、event_news_items 复合唯一、run_llm_job 是纯计算），
  MVP 接受该窗口；需要更强保证时改为 watchdog 续期（未实现）。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger

try:  # pragma: no cover - redis 是 hard dependency，留 import-guard 给纯本地环境
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

logger = get_logger("lock")

# 进程内兜底锁池。key → asyncio.Lock。
_local_locks: dict[str, asyncio.Lock] = {}

# Lua：原子"值匹配则删除"。KEYS[1]=key，ARGV[1]=token。
_RELEASE_IF_MATCH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


@asynccontextmanager
async def try_lock(key: str, *, ttl_s: int) -> AsyncIterator[bool]:
    """尝试获取分布式锁，非阻塞。

    Yields:
        True  — 获得锁，退出时自动释放
        False — 未获得（已被别人持有或 redis 故障+本地也被占），**不得进入临界区**
    """
    acquired, release = await _acquire(key, ttl_s)
    try:
        yield acquired
    finally:
        if acquired and release is not None:
            try:
                await release()
            except Exception as e:  # pragma: no cover
                logger.warning("lock_release_failed", key=key, error=str(e)[:120])


async def _acquire(key: str, ttl_s: int):
    """返回 (acquired, release_callable | None)。"""
    # 路径 1：Redis
    if aioredis is not None:
        client = None
        token = uuid.uuid4().hex
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            got = bool(await client.set(name=key, value=token, nx=True, ex=ttl_s))
        except Exception as e:
            got = False
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
                client = None
            logger.warning("lock_redis_unreachable", key=key, error=str(e)[:120])
            # 继续走本地兜底
        else:
            if got:
                captured_client = client
                captured_token = token

                async def release() -> None:
                    try:
                        # 只有 GET key == token 才 DEL；超 TTL 被别人拿走时返回 0，不误删。
                        result = await captured_client.eval(
                            _RELEASE_IF_MATCH, 1, key, captured_token
                        )
                        if result == 0:
                            logger.warning(
                                "lock_expired_before_release",
                                key=key,
                                note="TTL 已过，锁可能已被别人持有；本次未执行 DEL",
                            )
                    finally:
                        await captured_client.aclose()

                return True, release
            # Redis 正常但锁已被别人持有：**不回落本地锁**，直接返回 False
            try:
                await client.aclose()
            except Exception:
                pass
            return False, None

    # 路径 2：进程内兜底（仅当 aioredis 不可用时）
    lock = _local_locks.setdefault(key, asyncio.Lock())
    if lock.locked():
        return False, None
    await lock.acquire()

    async def release() -> None:
        if lock.locked():
            lock.release()

    return True, release
