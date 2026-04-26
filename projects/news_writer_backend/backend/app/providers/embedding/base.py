"""EmbeddingProvider 抽象。"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, texts: list[str], *, timeout_s: float = 25.0) -> list[list[float]]:
        """返回与 texts 等长的 embedding 列表。"""
