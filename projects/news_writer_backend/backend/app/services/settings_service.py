"""应用运行时设置 service。

配置读取优先级（shared §10）：
    value = app_settings[key] ?? env[KEY_UPPERCASE]

已知 key：llm_base_url / llm_model / embedding_base_url / embedding_model。
api_key 始终从 env 读，**不**进入 app_settings。

Step 12 会在此基础上扩展 HTTP API：GET /settings/model & PATCH /settings/model。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.app_setting import AppSetting

KNOWN_KEYS = (
    "llm_base_url",
    "llm_model",
    "embedding_base_url",
    "embedding_model",
)


@dataclass
class EffectiveValue:
    value: str
    source: str  # "db" | "env"


async def _load_db_map(session: AsyncSession, keys: Iterable[str]) -> dict[str, str]:
    rows = (
        await session.execute(select(AppSetting).where(AppSetting.key.in_(tuple(keys))))
    ).scalars().all()
    return {r.key: (r.value or "") for r in rows}


def _env_default(key: str) -> str:
    return {
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_model": settings.embedding_model,
    }[key]


async def _resolve(keys: Iterable[str]) -> dict[str, EffectiveValue]:
    async with SessionLocal() as session:
        db_map = await _load_db_map(session, keys)
    result: dict[str, EffectiveValue] = {}
    for k in keys:
        if k in db_map and db_map[k]:
            result[k] = EffectiveValue(value=db_map[k], source="db")
        else:
            result[k] = EffectiveValue(value=_env_default(k), source="env")
    return result


async def get_effective_llm_config() -> dict:
    """给 LLM Router 用：返回当前生效的 llm_base_url / llm_model。"""
    m = await _resolve(("llm_base_url", "llm_model"))
    return {"llm_base_url": m["llm_base_url"].value, "llm_model": m["llm_model"].value}


async def get_effective_embedding_config() -> dict:
    m = await _resolve(("embedding_base_url", "embedding_model"))
    return {
        "embedding_base_url": m["embedding_base_url"].value,
        "embedding_model": m["embedding_model"].value,
    }


async def get_model_settings_full() -> dict:
    """GET /settings/model 响应 body。"""
    m = await _resolve(KNOWN_KEYS)
    return {
        "llm_base_url": m["llm_base_url"].value,
        "llm_model": m["llm_model"].value,
        "llm_api_key_configured": bool(settings.llm_api_key),
        "source": {k: m[k].source for k in ("llm_base_url", "llm_model")},
    }


async def patch_model_settings(
    session: AsyncSession,
    *,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
) -> dict:
    """PATCH /settings/model：upsert 非 None 字段，然后 invalidate cache。"""
    updates = {
        k: v for k, v in (("llm_base_url", llm_base_url), ("llm_model", llm_model)) if v is not None
    }
    for key, value in updates.items():
        existing = (
            await session.execute(select(AppSetting).where(AppSetting.key == key))
        ).scalar_one_or_none()
        if existing is None:
            session.add(AppSetting(key=key, value=value))
        else:
            existing.value = value
    await session.commit()

    # 通知本 worker + 其它 worker 清 LLM provider cache
    from app.core.cache_bus import publish_invalidation

    await publish_invalidation("model_settings")
    return await get_model_settings_full()
