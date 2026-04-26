"""LLM Service：加载 prompt 模板、渲染变量、调 provider、记 llm_jobs。"""

from __future__ import annotations

import time
from pathlib import Path
from string import Template
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.errors import LLMTimeout, LLMUnavailable
from app.core.logging import get_logger
from app.models.llm_job import LlmJob
from app.providers.llm.router import get_llm_provider

PROMPT_DIR = Path(__file__).parent.parent / "prompts"

SYSTEM_MARK = "---SYSTEM---"
USER_MARK = "---USER---"

logger = get_logger("llm")


def _load_template(prompt_template_id: str) -> tuple[str, str]:
    tpl_path = PROMPT_DIR / f"{prompt_template_id}.md"
    if not tpl_path.exists():
        raise LLMUnavailable(f"prompt 模板不存在：{prompt_template_id}")
    raw = tpl_path.read_text(encoding="utf-8")
    if SYSTEM_MARK not in raw or USER_MARK not in raw:
        raise LLMUnavailable(f"prompt 模板格式错误：{prompt_template_id}")
    _, rest = raw.split(SYSTEM_MARK, 1)
    system_part, user_part = rest.split(USER_MARK, 1)
    return system_part.strip(), user_part.strip()


def _render(text: str, variables: dict[str, Any]) -> str:
    """用 string.Template 做 ${var} 替换。缺失变量保留占位符（不抛错）。"""
    return Template(text).safe_substitute({k: _stringify(v) for k, v in variables.items()})


def _stringify(value: Any) -> str:
    import json

    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


async def run_llm_job(
    session: AsyncSession,
    *,
    job_type: str,
    prompt_template_id: str,
    variables: dict[str, Any],
    timeout_s: float = 45.0,
) -> dict:
    """加载 prompt，渲染，调 LLM，写 llm_jobs。

    成功返回解析后的 dict；失败抛 LLMTimeout / LLMUnavailable。
    """
    system_tpl, user_tpl = _load_template(prompt_template_id)
    system = _render(system_tpl, variables)
    user = _render(user_tpl, variables)

    provider = await get_llm_provider()
    started = time.monotonic()

    status = "failed"
    result: dict | None = None
    error: str | None = None
    try:
        result = await provider.chat_json(system, user, timeout_s=timeout_s)
        status = "success"
        return result
    except LLMTimeout as e:
        status = "timeout"
        error = e.message
        raise
    except LLMUnavailable as e:
        status = "failed"
        error = e.message
        raise
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # 不保存 prompt 原文；只记录变量 keys
        record = LlmJob(
            id=str(ULID()),
            job_type=job_type,
            status=status,
            prompt_template_id=prompt_template_id,
            request_payload={"variable_keys": list(variables.keys())},
            response_payload=result if isinstance(result, (dict, list)) else None,
            error_message=error,
            elapsed_ms=elapsed_ms,
            model=getattr(provider, "model", None),
        )
        session.add(record)
        try:
            await session.commit()
        except Exception:  # pragma: no cover
            await session.rollback()
        logger.info(
            "llm_job_done",
            job_type=job_type,
            template=prompt_template_id,
            status=status,
            elapsed_ms=elapsed_ms,
        )
