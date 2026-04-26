"""/api/v1/health — 存活探针 + 子系统健康。"""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.base import SessionLocal

try:  # 延迟依赖，某些测试环境可能没有 redis
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

router = APIRouter()

APP_VERSION = "0.1.0"


async def _check_db() -> str:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "fail"


async def _check_redis() -> str:
    if aioredis is None:
        return "fail"
    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
        return "ok" if pong else "fail"
    except Exception:
        return "fail"


async def _resolve_llm_base_url() -> str:
    """运行时生效的 LLM base_url：DB override > env（与业务调用走同一条路径）。"""
    try:
        from app.services.settings_service import get_effective_llm_config

        cfg = await get_effective_llm_config()
        return cfg.get("llm_base_url") or ""
    except Exception:
        # DB 不可用或 settings_service 挂了，退回 env 值避免 /health 本身炸
        return settings.llm_base_url


async def _check_llm(base: str) -> str:
    if not base:
        return "fail"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(base)
        return "ok" if resp.status_code < 600 else "fail"
    except Exception:
        return "fail"


@router.get("/health")
async def health() -> dict:
    db_status = await _check_db()
    redis_status = await _check_redis()
    llm_base = await _resolve_llm_base_url()
    llm_status = await _check_llm(llm_base)
    overall = "ok" if all(s == "ok" for s in (db_status, redis_status, llm_status)) else "degraded"
    return {
        "status": overall,
        "version": APP_VERSION,
        "checks": {"db": db_status, "redis": redis_status, "llm": llm_status},
        "env": settings.app_env,
        # 调试友好：把 /health 当前实际 ping 的 LLM 地址透出，便于 PATCH /settings/model 后核对
        "llm_base_url": llm_base,
    }
