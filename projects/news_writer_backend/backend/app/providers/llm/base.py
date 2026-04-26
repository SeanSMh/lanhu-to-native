"""LLM Provider 抽象。"""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    """统一的 LLM 接口。

    实现层负责：
    - 调 chat completions 接口
    - 要求返回合法 JSON（借助 response_format 或 fallback 正则抽取）
    - 超时 → 抛 LLMTimeout；其它失败 → 抛 LLMUnavailable
    """

    model: str

    async def chat_json(self, system: str, user: str, *, timeout_s: float = 25.0) -> dict:
        ...
