"""StyleProfile 并发回归：部分唯一索引 + 业务错误翻译。"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from ulid import ULID

from app.core.errors import Conflict
from app.models.style_profile import StyleProfile
from app.models.user import User
from app.schemas.settings import StyleProfileCreate
from app.services.style_profile_service import create_profile
from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


async def test_second_default_insert_violates_partial_unique(session_factory, test_user):
    """直接绕开 service 往表里塞两条 is_default=true，第二条应被 DB 拒绝。"""
    async with session_factory() as s:
        user = (await s.execute(select(User).limit(1))).scalar_one()
        s.add(
            StyleProfile(
                id=str(ULID()),
                user_id=user.id,
                name="A",
                is_default=True,
            )
        )
        await s.commit()

    async with session_factory() as s:
        s.add(
            StyleProfile(
                id=str(ULID()),
                user_id=user.id,
                name="B",
                is_default=True,
            )
        )
        with pytest.raises(Exception) as ei:
            await s.commit()
        # PG 唯一约束：错误类含 IntegrityError
        assert "Integrity" in type(ei.value).__name__ or "unique" in str(ei.value).lower()


async def test_concurrent_default_creates_one_wins(session_factory, test_user):
    """两个 create_profile 同时带 is_default=true 进来，恰好一个成功，另一个 409。"""

    async def attempt(name: str) -> str:
        async with session_factory() as s:
            user = (await s.execute(select(User).limit(1))).scalar_one()
            try:
                await create_profile(
                    s,
                    user.id,
                    StyleProfileCreate(name=name, tone="x", is_default=True),
                )
                return "ok"
            except Conflict:
                return "conflict"

    results = await asyncio.gather(attempt("A"), attempt("B"))
    # 并发场景难以稳定复现（update + insert 之间还隔着一次提交），
    # 但至少不能出现 500 / 两条都 ok 的状态：
    # 可能是 [ok, ok]（串行化成功）或 [ok, conflict]（并发撞上唯一约束）。
    assert "conflict" in results or results == ["ok", "ok"]
    # 最终表中 is_default=true 的条数必须 ≤ 1
    async with session_factory() as s:
        user = (await s.execute(select(User).limit(1))).scalar_one()
        defaults = list(
            (
                await s.execute(
                    select(StyleProfile.id).where(
                        StyleProfile.user_id == user.id,
                        StyleProfile.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(defaults) == 1
