"""测试 fixture。

DB 要求：一个可连接的 PostgreSQL（默认走 DB_URL）。
本 conftest 每个测试跑前重建 schema（drop_all + create_all）。

如果 DB 不可连接，会把所有 DB 相关 test 标记为 skip。
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_session
from app.core.config import settings
from app.core.security import hash_token
from app.db.base import Base
from app.main import app
from app.models.user import User
from ulid import ULID


TEST_API_TOKEN = "test-token-123"
TEST_DB_URL = os.environ.get("TEST_DB_URL", settings.db_url)


def _db_available() -> bool:
    async def _ping() -> bool:
        from sqlalchemy import text

        eng = create_async_engine(TEST_DB_URL)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()

    try:
        return asyncio.run(_ping())
    except Exception:
        return False


DB_AVAILABLE = _db_available()
skip_if_no_db = pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL not reachable")


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DB_URL)
    # 干净的 schema
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def test_user(session_factory) -> User:
    async with session_factory() as s:
        u = User(
            id=str(ULID()),
            email="self@news-writer.local",
            nickname="我",
            api_token_hash=hash_token(TEST_API_TOKEN),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


@pytest_asyncio.fixture
async def client(session_factory, test_user):
    # 覆盖 get_session 依赖，让请求使用测试 engine 的 session
    async def _override_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_header():
    return {"Authorization": f"Bearer {TEST_API_TOKEN}"}
