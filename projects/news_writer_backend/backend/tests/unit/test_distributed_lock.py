"""分布式锁在 Redis 不可达时的本地兜底语义。

这些测试不依赖 Redis；通过打桩让 aioredis 表现为"无法创建 client"。
"""

from __future__ import annotations

import asyncio

import pytest

import app.core.distributed_lock as dl


@pytest.mark.asyncio
async def test_local_fallback_two_concurrent_only_one_gets(monkeypatch):
    # 假装 aioredis 不存在 → 走进程内兜底锁
    monkeypatch.setattr(dl, "aioredis", None)
    # 清空全局字典避免跨测试污染
    dl._local_locks.clear()

    key = "unit:test:only_one"
    results: list[bool] = []

    async def attempt():
        async with dl.try_lock(key, ttl_s=30) as got:
            results.append(got)
            if got:
                await asyncio.sleep(0.05)

    await asyncio.gather(attempt(), attempt())
    assert sorted(results) == [False, True]


@pytest.mark.asyncio
async def test_local_fallback_releases_after_exit(monkeypatch):
    monkeypatch.setattr(dl, "aioredis", None)
    dl._local_locks.clear()

    key = "unit:test:release"
    async with dl.try_lock(key, ttl_s=30) as got:
        assert got is True
    # 释放后再来一次应能拿到
    async with dl.try_lock(key, ttl_s=30) as got2:
        assert got2 is True


@pytest.mark.asyncio
async def test_redis_unreachable_falls_back(monkeypatch):
    """模拟 redis 返回异常，应回落到本地锁而不是崩溃。"""

    class _BadRedis:
        @staticmethod
        def from_url(*args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(dl, "aioredis", _BadRedis)
    dl._local_locks.clear()

    key = "unit:test:fallback"
    async with dl.try_lock(key, ttl_s=30) as got:
        assert got is True


# ---------- Redis 锁安全性回归（不误删别人的锁） ----------


class _FakeRedisClient:
    """极简内存 redis：记录 key→value、实现 set(nx,ex)、eval、delete、aclose。"""

    def __init__(self, store: dict[str, str]):
        self.store = store
        self.eval_calls: list[tuple[str, list, str]] = []
        self.delete_calls: list[str] = []
        self.closed = False

    async def set(self, *, name: str, value: str, nx: bool = False, ex: int = 0):
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    async def eval(self, script, numkeys, *args):
        # 模拟 Lua：GET key == ARGV[1] ? DEL key : 0
        key = args[0]
        token = args[1]
        self.eval_calls.append((script, list(args), self.store.get(key, "")))
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0

    async def delete(self, key):
        self.delete_calls.append(key)
        self.store.pop(key, None)

    async def aclose(self):
        self.closed = True


def _install_fake_redis(monkeypatch, shared_store: dict[str, str]):
    clients_created: list[_FakeRedisClient] = []

    class _Module:
        @staticmethod
        def from_url(*args, **kwargs):
            c = _FakeRedisClient(shared_store)
            clients_created.append(c)
            return c

    monkeypatch.setattr(dl, "aioredis", _Module)
    return clients_created


@pytest.mark.asyncio
async def test_redis_release_uses_eval_not_delete(monkeypatch):
    """正常路径：释放走 Lua EVAL 做 token 匹配，不是裸 DELETE。"""
    store: dict[str, str] = {}
    clients = _install_fake_redis(monkeypatch, store)

    async with dl.try_lock("unit:redis:normal", ttl_s=30) as got:
        assert got is True
    # 进入锁阶段至少创建了 1 个 client
    assert clients, "expected at least one fake client"
    # 成功获得锁的那个 client 应该调了 eval，而不是 delete
    owning_client = next(c for c in clients if c.eval_calls)
    assert owning_client.eval_calls, "release should call EVAL"
    assert owning_client.delete_calls == [], "release must NOT use bare DELETE"
    # store 中该 key 应被真正删除
    assert "unit:redis:normal" not in store


@pytest.mark.asyncio
async def test_redis_release_after_ttl_expiry_does_not_delete_others_lock(monkeypatch):
    """核心回归：Worker A 超 TTL → Worker B 拿到锁 → A 释放时不得删掉 B 的锁。"""
    store: dict[str, str] = {}
    clients = _install_fake_redis(monkeypatch, store)

    key = "unit:redis:ttl_expiry"

    # Worker A 拿锁
    acquired_a, release_a = await dl._acquire(key, ttl_s=30)
    assert acquired_a is True
    a_token = store[key]

    # 模拟 TTL 到期：Redis 丢掉 A 的 key
    del store[key]

    # Worker B 进来拿到了（全新 token）
    acquired_b, release_b = await dl._acquire(key, ttl_s=30)
    assert acquired_b is True
    b_token = store[key]
    assert b_token != a_token, "B 的 token 必须与 A 不同"

    # Worker A 现在退出 async with → 调自己的 release。**不得删 B 的 key**
    await release_a()  # type: ignore[misc]
    assert key in store, "A 的 release 不得删掉 B 持有的锁"
    assert store[key] == b_token, "B 的 token 必须原样保留"

    # B 正常释放，才真正 DEL
    await release_b()  # type: ignore[misc]
    assert key not in store
