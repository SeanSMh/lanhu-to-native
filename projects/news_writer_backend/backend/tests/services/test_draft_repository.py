"""DraftRepository 并发回归：两个同时拿 base_version=1 的请求，只有一个应该赢。"""

from __future__ import annotations

import asyncio

import pytest
from ulid import ULID

from app.core.errors import DraftNotFound, DraftVersionConflict
from app.models.draft import Draft
from app.models.event import Event
from app.repositories.draft_repository import DraftRepository
from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


async def _seed(session_factory) -> tuple[str, int]:
    async with session_factory() as s:
        evt = Event(id=str(ULID()), title="e", status="active")
        s.add(evt)
        await s.flush()
        draft_id = str(ULID())
        # 草稿所在 user_id 跑测试时 conftest.test_user 已建好
        from app.models.user import User
        from sqlalchemy import select

        user = (await s.execute(select(User).limit(1))).scalar_one()
        s.add(
            Draft(
                id=draft_id,
                event_id=evt.id,
                user_id=user.id,
                title="t0",
                angle_type="trend",
                outline_json=[],
                content_markdown="",
                status="editing",
                word_count=0,
                version=1,
            )
        )
        await s.commit()
    return draft_id, 1


async def test_concurrent_updates_exactly_one_wins(session_factory, test_user):
    draft_id, base_version = await _seed(session_factory)

    async def attempt(label: str) -> str:
        async with session_factory() as s:
            repo = DraftRepository(s)
            try:
                await repo.update_with_version(
                    draft_id, base_version, {"title": f"from-{label}"}
                )
                return "ok"
            except DraftVersionConflict:
                return "conflict"

    results = await asyncio.gather(attempt("A"), attempt("B"))
    # 两个请求基于同一 base_version=1 进来，必须一个 ok 一个 409
    assert sorted(results) == ["conflict", "ok"], results


async def test_update_not_found_returns_not_found(session_factory, test_user):
    async with session_factory() as s:
        repo = DraftRepository(s)
        with pytest.raises(DraftNotFound):
            await repo.update_with_version(
                "01HDOESNOTEXIST0000000000A", 1, {"title": "x"}
            )


async def test_update_stale_version_raises_conflict(session_factory, test_user):
    draft_id, _ = await _seed(session_factory)
    # 先推进一次
    async with session_factory() as s:
        await DraftRepository(s).update_with_version(draft_id, 1, {"title": "v2"})
    # 再拿老 base_version
    async with session_factory() as s:
        with pytest.raises(DraftVersionConflict) as ei:
            await DraftRepository(s).update_with_version(draft_id, 1, {"title": "v?"})
        assert ei.value.details["current_version"] == 2
