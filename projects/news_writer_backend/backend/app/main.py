"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.middleware import RequestContextMiddleware
from app.api.v1.auth import router as auth_router
from app.api.v1.drafts import router as drafts_router
from app.api.v1.events import router as events_router
from app.api.v1.health import router as health_router
from app.api.v1.images import router as images_router
from app.api.v1.images import slots_router as image_slots_router
from app.api.v1.settings import settings_router, style_router
from app.api.v1.writing import router as writing_router
from app.bootstrap import run_bootstrap
from app.core.cache_bus import run_subscriber
from app.core.errors import (
    AppError,
    app_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging, get_logger
from app.tasks.scheduler import start_scheduler, stop_scheduler

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_bootstrap()
    except Exception as e:  # pragma: no cover
        logger.warning("bootstrap_failed", error=str(e))
    sub_task = asyncio.create_task(run_subscriber())
    try:
        start_scheduler()
    except Exception as e:  # pragma: no cover
        logger.warning("scheduler_start_failed", error=str(e))
    try:
        yield
    finally:
        stop_scheduler()
        sub_task.cancel()
        try:
            await sub_task
        except Exception:
            pass


app = FastAPI(title="news_writer backend", version="0.1.0", lifespan=lifespan)

# 中间件
app.add_middleware(RequestContextMiddleware)

# 错误处理器
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)

# 路由
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(auth_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(drafts_router, prefix="/api/v1")
app.include_router(writing_router, prefix="/api/v1")
app.include_router(images_router, prefix="/api/v1")
app.include_router(image_slots_router, prefix="/api/v1")
app.include_router(style_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
