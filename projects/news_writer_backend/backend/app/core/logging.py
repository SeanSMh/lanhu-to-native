"""structlog 配置 + 敏感字段脱敏 processor。

日志禁止打印：Authorization 头完整值、api_token / api_key、LLM 请求 body 原文。
可以打印：ID、timestamp、endpoint、status、耗时。
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import settings
from app.core.request_context import get_request_id

# 敏感字段名（不区分大小写）
_SENSITIVE_KEYS = {
    "authorization",
    "api_token",
    "api_key",
    "auth_initial_api_token",
    "llm_api_key",
    "embedding_api_key",
    "image_search_api_key",
    "storage_secret_key",
}

_TOKEN_LIKE_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        # Bearer xxx 原文在字符串里
        return _TOKEN_LIKE_RE.sub(r"\1[REDACTED]", value)
    return value


def redact_processor(logger, method_name, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        low = key.lower()
        if low in _SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
            continue
        event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def add_request_id(logger, method_name, event_dict: dict) -> dict:
    event_dict["request_id"] = get_request_id()
    return event_dict


def configure_logging() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_request_id,
        structlog.processors.add_log_level,
        timestamper,
        redact_processor,
        # exc_info=<exc> → 格式化成 traceback 字符串字段
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if settings.is_dev:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # stdlib logging 也统一一下
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def get_logger(name: str = "app") -> Any:
    return structlog.get_logger(name)
