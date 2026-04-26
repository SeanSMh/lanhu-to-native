"""Draft 数据访问层。乐观锁在此实现。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DraftNotFound, DraftVersionConflict
from app.models.draft import Draft
from app.utils.cursor import decode_cursor, encode_cursor


class DraftRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def get(self, draft_id: str) -> Draft | None:
        return (
            await self.s.execute(select(Draft).where(Draft.id == draft_id))
        ).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[Draft], str | None]:
        q = select(Draft).where(Draft.user_id == user_id)
        if status:
            q = q.where(Draft.status == status)
        else:
            q = q.where(Draft.status != "archived")

        cursor_data = decode_cursor(cursor)
        if cursor_data:
            c_ts = datetime.fromisoformat(cursor_data["updated_at"])
            c_id = cursor_data["id"]
            q = q.where(
                or_(
                    Draft.updated_at < c_ts,
                    and_(Draft.updated_at == c_ts, Draft.id < c_id),
                )
            )

        rows = list(
            (
                await self.s.execute(
                    q.order_by(Draft.updated_at.desc(), Draft.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                {"updated_at": last.updated_at.isoformat(), "id": last.id}
            )
            rows = rows[:limit]
        return rows, next_cursor

    async def add(self, draft: Draft) -> Draft:
        self.s.add(draft)
        await self.s.commit()
        await self.s.refresh(draft)
        return draft

    async def update_with_version(
        self, draft_id: str, base_version: int, patch: dict[str, Any]
    ) -> Draft:
        """乐观锁更新。原子 UPDATE ... WHERE version=? RETURNING id；无命中则区分
        not-found 与 version-conflict 再抛错，避免 TOCTOU。

        patch 不应包含 version / updated_at 字段，函数内部补上 version += 1。
        """
        patch = dict(patch)
        patch["version"] = base_version + 1
        result = await self.s.execute(
            update(Draft)
            .where(Draft.id == draft_id, Draft.version == base_version)
            .values(**patch)
            .returning(Draft.id)
        )
        updated_id = result.scalar_one_or_none()
        if updated_id is None:
            # 要么 draft 不存在，要么 version 已被别人推进
            await self.s.rollback()
            current = await self.get(draft_id)
            if current is None:
                raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
            raise DraftVersionConflict(
                "草稿已被其它操作更新，请刷新后重试",
                {"current_version": current.version, "base_version": base_version},
            )
        await self.s.commit()
        refreshed = await self.get(draft_id)
        assert refreshed is not None
        return refreshed

    async def force_update(self, draft_id: str, patch: dict[str, Any]) -> Draft:
        await self.s.execute(update(Draft).where(Draft.id == draft_id).values(**patch))
        await self.s.commit()
        d = await self.get(draft_id)
        assert d is not None
        return d
