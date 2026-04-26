"""统一错误 schema（shared-conventions §5）。

所有失败响应：HTTP status + {code, message, details?}。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or None
        super().__init__(message)


class ValidationFailed(AppError):
    code = "validation_error"
    status_code = 422


class Unauthorized(AppError):
    code = "unauthorized"
    status_code = 401


class EventNotFound(AppError):
    code = "event_not_found"
    status_code = 404


class DraftNotFound(AppError):
    code = "draft_not_found"
    status_code = 404


class ImageNotFound(AppError):
    code = "image_not_found"
    status_code = 404


class StyleProfileNotFound(AppError):
    code = "style_profile_not_found"
    status_code = 404


class Conflict(AppError):
    code = "conflict"
    status_code = 409


class DraftVersionConflict(AppError):
    code = "draft_version_conflict"
    status_code = 409


class LLMUnavailable(AppError):
    code = "llm_unavailable"
    status_code = 503


class LLMTimeout(AppError):
    code = "llm_timeout"
    status_code = 503


class NewsSourceFailed(AppError):
    code = "news_source_failed"
    status_code = 503


class ImageSearchFailed(AppError):
    code = "image_search_failed"
    status_code = 503


def _json(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body: dict = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content=body)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _json(exc.status_code, exc.code, exc.message, exc.details)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # FastAPI 的请求体/查询参数校验失败
    return _json(
        422,
        "validation_error",
        "请求参数不合法",
        {"errors": exc.errors()[:10]},  # 只带前 10 条避免过大
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：不把堆栈透给客户端，但完整记入日志（含 traceback）。"""
    # 延迟 import 避免循环
    from app.core.logging import get_logger

    logger = get_logger("errors")
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
        error=str(exc)[:500],
        exc_info=exc,
    )
    return _json(500, "internal_error", "服务器内部错误")
