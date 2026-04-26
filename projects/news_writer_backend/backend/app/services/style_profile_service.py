"""StyleProfile CRUD service。

并发安全：`is_default=true` 的唯一性由表上的部分唯一索引兜底
（见 migration 0002_unique_default_style）。本 service 内部先把别的 default
清掉再提交，正常路径不触发约束；极端并发下 IntegrityError 会被翻译成 409。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.errors import Conflict, StyleProfileNotFound
from app.models.style_profile import StyleProfile
from app.schemas.settings import (
    StyleProfileCreate,
    StyleProfileOut,
    StyleProfileUpdate,
)


def _to_out(row: StyleProfile) -> StyleProfileOut:
    return StyleProfileOut(
        id=row.id,
        name=row.name,
        tone=row.tone,
        forbidden_words=list(row.forbidden_words_json or []),
        preferred_structure=row.preferred_structure,
        paragraph_style=row.paragraph_style,
        headline_style=row.headline_style,
        prompt_preset=row.prompt_preset,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_profiles(session: AsyncSession, user_id: str) -> list[StyleProfileOut]:
    rows = list(
        (
            await session.execute(
                select(StyleProfile)
                .where(StyleProfile.user_id == user_id)
                .order_by(StyleProfile.is_default.desc(), StyleProfile.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows]


async def create_profile(
    session: AsyncSession, user_id: str, payload: StyleProfileCreate
) -> StyleProfileOut:
    row = StyleProfile(
        id=str(ULID()),
        user_id=user_id,
        name=payload.name,
        tone=payload.tone,
        forbidden_words_json=list(payload.forbidden_words or []),
        preferred_structure=payload.preferred_structure,
        paragraph_style=payload.paragraph_style,
        headline_style=payload.headline_style,
        prompt_preset=payload.prompt_preset,
        is_default=payload.is_default,
    )
    if payload.is_default:
        await session.execute(
            update(StyleProfile)
            .where(StyleProfile.user_id == user_id, StyleProfile.is_default.is_(True))
            .values(is_default=False)
        )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise Conflict(
            "默认风格并发冲突，请刷新后重试",
            {"user_id": user_id, "reason": "duplicate_default"},
        ) from e
    await session.refresh(row)
    return _to_out(row)


async def update_profile(
    session: AsyncSession, user_id: str, profile_id: str, payload: StyleProfileUpdate
) -> StyleProfileOut:
    row = (
        await session.execute(
            select(StyleProfile).where(
                StyleProfile.id == profile_id, StyleProfile.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise StyleProfileNotFound("风格配置不存在", {"id": profile_id})
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default") is True:
        await session.execute(
            update(StyleProfile)
            .where(
                StyleProfile.user_id == user_id,
                StyleProfile.id != profile_id,
                StyleProfile.is_default.is_(True),
            )
            .values(is_default=False)
        )
    if "forbidden_words" in data:
        data["forbidden_words_json"] = list(data.pop("forbidden_words") or [])
    for k, v in data.items():
        setattr(row, k, v)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise Conflict(
            "默认风格并发冲突，请刷新后重试",
            {"id": profile_id, "reason": "duplicate_default"},
        ) from e
    await session.refresh(row)
    return _to_out(row)


async def delete_profile(session: AsyncSession, user_id: str, profile_id: str) -> None:
    row = (
        await session.execute(
            select(StyleProfile).where(
                StyleProfile.id == profile_id, StyleProfile.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise StyleProfileNotFound("风格配置不存在", {"id": profile_id})
    if row.is_default:
        raise Conflict("不能删除默认风格", {"id": profile_id})
    await session.delete(row)
    await session.commit()
