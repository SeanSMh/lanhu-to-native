"""LLM Provider 工厂 + 1 分钟 TTL cache。

运行时配置（llm_base_url / llm_model）从 app_settings 表读，fall back 到 env。
PATCH /settings/model 成功后应调用 invalidate_llm_router_cache()。
"""

from __future__ import annotations

import time

from app.core.config import settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_compat import OpenAICompatibleProvider

_CACHE_TTL_S = 60.0
_cache: dict = {"provider": None, "at": 0.0}


def invalidate_llm_router_cache() -> None:
    _cache["provider"] = None
    _cache["at"] = 0.0


async def get_llm_provider() -> LLMProvider:
    """返回当前生效的 LLM provider。

    FAKE_LLM=true 时始终返回 FakeLLMProvider。
    """
    if settings.fake_llm:
        return FakeLLMProvider()
    now = time.monotonic()
    if _cache["provider"] is not None and (now - _cache["at"]) < _CACHE_TTL_S:
        return _cache["provider"]

    # 从 SettingsService 拿实时值；该 service 处理 DB override > env
    # 延迟 import 避免循环
    from app.services.settings_service import get_effective_llm_config

    cfg = await get_effective_llm_config()
    provider = OpenAICompatibleProvider(
        base_url=cfg["llm_base_url"],
        api_key=settings.llm_api_key,  # api_key 始终来自 env
        model=cfg["llm_model"],
    )
    _cache["provider"] = provider
    _cache["at"] = now
    return provider
