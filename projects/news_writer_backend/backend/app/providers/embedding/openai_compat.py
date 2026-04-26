"""OpenAI 兼容 embedding provider（硅基流动 bge-m3 / OpenAI 等）。"""

from __future__ import annotations

import httpx

from app.core.errors import LLMTimeout, LLMUnavailable


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, *, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str], *, timeout_s: float = 25.0) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise LLMUnavailable("EMBEDDING_API_KEY 未配置")
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMTimeout("Embedding 调用超时") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable("Embedding 网络错误", {"error": str(e)[:200]}) from e
        if resp.status_code >= 400:
            raise LLMUnavailable(
                "Embedding 调用失败",
                {"status": resp.status_code, "body_preview": resp.text[:200]},
            )
        try:
            body = resp.json()
            items = body["data"]
            return [row["embedding"] for row in items]
        except Exception as e:
            raise LLMUnavailable("Embedding 响应结构异常", {"error": str(e)[:200]}) from e
