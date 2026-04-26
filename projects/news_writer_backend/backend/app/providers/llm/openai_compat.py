"""OpenAI 兼容 Provider（DeepSeek / 硅基流动 / OpenRouter 等都能用）。"""

from __future__ import annotations

import json
import re

import httpx

from app.core.errors import LLMTimeout, LLMUnavailable


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BRACE_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json(content: str) -> dict:
    """尽力从 content 中提取合法 JSON（dict）。"""
    content = content.strip()
    # 1. 直接解析
    try:
        obj = json.loads(content)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # 2. fenced block
    m = _JSON_BLOCK_RE.search(content)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    # 3. 首个大括号块
    m = _JSON_BRACE_RE.search(content)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise LLMUnavailable("LLM 未返回合法 JSON", {"raw_preview": content[:200]})


class OpenAICompatibleProvider:
    """调用 OpenAI 兼容的 /chat/completions。"""

    def __init__(self, *, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat_json(self, system: str, user: str, *, timeout_s: float = 25.0) -> dict:
        if not self.api_key:
            raise LLMUnavailable("LLM api_key 未配置")
        url = f"{self.base_url}/chat/completions"
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMTimeout("LLM 调用超时", {"model": self.model}) from e
        except httpx.HTTPError as e:
            raise LLMUnavailable("LLM 网络错误", {"error": str(e)[:200]}) from e

        if resp.status_code >= 500:
            raise LLMUnavailable(
                "LLM 上游服务错误",
                {"status": resp.status_code, "body_preview": resp.text[:200]},
            )
        if resp.status_code == 400:
            # 可能是不支持 response_format，回退一次
            fallback = dict(payload)
            fallback.pop("response_format", None)
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.post(url, json=fallback, headers=headers)
            except httpx.TimeoutException as e:
                raise LLMTimeout("LLM 调用超时", {"model": self.model}) from e
            except httpx.HTTPError as e:
                raise LLMUnavailable("LLM 网络错误", {"error": str(e)[:200]}) from e
        if resp.status_code >= 400:
            raise LLMUnavailable(
                "LLM 调用失败",
                {"status": resp.status_code, "body_preview": resp.text[:200]},
            )

        try:
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMUnavailable("LLM 响应结构异常", {"error": str(e)[:200]}) from e
        return _extract_json(content)
