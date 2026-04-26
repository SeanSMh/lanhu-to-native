"""Embedding provider 工厂 + TTL cache（规则同 LLM router）。"""

from __future__ import annotations

import time

from app.core.config import settings
from app.providers.embedding.base import EmbeddingProvider
from app.providers.embedding.fake import FakeEmbeddingProvider
from app.providers.embedding.openai_compat import OpenAICompatibleEmbeddingProvider

_TTL = 60.0
_cache: dict = {"provider": None, "at": 0.0}


def invalidate_embedding_cache() -> None:
    _cache["provider"] = None
    _cache["at"] = 0.0


async def get_embedding_provider() -> EmbeddingProvider:
    if settings.fake_llm:
        return FakeEmbeddingProvider()
    now = time.monotonic()
    if _cache["provider"] is not None and now - _cache["at"] < _TTL:
        return _cache["provider"]
    from app.services.settings_service import get_effective_embedding_config

    cfg = await get_effective_embedding_config()
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=cfg["embedding_base_url"],
        api_key=settings.embedding_api_key,
        model=cfg["embedding_model"],
    )
    _cache["provider"] = provider
    _cache["at"] = now
    return provider
