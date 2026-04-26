"""FastAPI 中间件：request id + 请求日志。"""

from __future__ import annotations

import time
from ulid import ULID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.request_context import set_request_id

logger = get_logger("http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求生成 request_id 并记录访问日志。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-Id") or str(ULID())
        set_request_id(req_id)
        started = time.monotonic()
        response: Response | None = None
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            status = response.status_code if response is not None else 500
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status,
                elapsed_ms=elapsed_ms,
                client=request.client.host if request.client else None,
            )
        if response is not None:
            response.headers["X-Request-Id"] = req_id
        return response
