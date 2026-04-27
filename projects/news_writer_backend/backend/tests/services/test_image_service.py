"""image_service 校验与 duplicate 原子性相关的单元/集成测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from ulid import ULID

from app.core.errors import Conflict, ValidationFailed
from app.models.draft import Draft
from app.models.event import Event
from app.models.image_asset import ImageAsset
from app.models.user import User
from app.services.draft_service import DraftService
from app.services.image_service import _validate_owner, upload_image
from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


# ---------- upload owner 校验 ----------


async def test_validate_owner_rejects_unknown_type(session):
    with pytest.raises(ValidationFailed) as ei:
        await _validate_owner(session, "lirbary", "01HX")
    assert ei.value.code == "validation_error"
    assert "owner_type" in (ei.value.details or {})


async def test_validate_owner_library_no_id_ok(session):
    # library 不需要 owner_id
    await _validate_owner(session, "library", None)


async def test_validate_owner_draft_requires_existing_owner(session):
    with pytest.raises(ValidationFailed) as ei:
        await _validate_owner(session, "draft", "01HDOESNOTEXIST0000000000A")
    assert "owner_id" in (ei.value.details or {}) or ei.value.details is not None


async def test_upload_rejects_unknown_owner_type(session):
    with pytest.raises(ValidationFailed):
        await upload_image(
            session,
            data=b"x",
            filename="x.jpg",
            owner_type="typo",
            owner_id=None,
        )


async def test_upload_draft_owner_id_missing(session):
    with pytest.raises(ValidationFailed):
        await upload_image(
            session,
            data=b"x",
            filename="x.jpg",
            owner_type="draft",
            owner_id=None,
        )


async def test_upload_library_drops_supplied_owner_id(session, monkeypatch):
    """owner_type=library 时，即使调用方传了 owner_id，也不得落库。"""
    from io import BytesIO

    from PIL import Image as PILImage

    # 构造 1x1 的真实 JPEG 字节
    buf = BytesIO()
    PILImage.new("RGB", (8, 8), "white").save(buf, format="JPEG")
    jpg_bytes = buf.getvalue()

    # 打桩 storage，避免真连 MinIO
    class _FakeStorage:
        async def put(self, key, data, *, content_type):
            return f"http://fake/{key}"

        async def delete(self, key):
            return None

    import app.services.image_service as svc

    monkeypatch.setattr(svc, "get_storage", lambda: _FakeStorage())

    result = await upload_image(
        session,
        data=jpg_bytes,
        filename="x.jpg",
        owner_type="library",
        owner_id="01DIRTYOWNER00000000000001",
    )

    row = (
        await session.execute(
            select(ImageAsset).where(ImageAsset.id == result.image_asset_id)
        )
    ).scalar_one()
    assert row.owner_type == "library"
    assert row.owner_id is None


# ---------- duplicate 原子性 ----------


async def _seed_draft_with_image(session) -> tuple[Draft, ImageAsset, User]:
    user = (await session.execute(select(User).limit(1))).scalar_one()
    evt = Event(id=str(ULID()), title="e", status="active")
    session.add(evt)
    await session.flush()
    draft = Draft(
        id=str(ULID()),
        event_id=evt.id,
        user_id=user.id,
        title="原稿",
        angle_type="trend",
        outline_json=[],
        content_markdown="",
        status="editing",
        word_count=0,
        version=1,
    )
    session.add(draft)
    await session.flush()
    img = ImageAsset(
        id=str(ULID()),
        owner_type="draft",
        owner_id=draft.id,
        source_type="search",
        image_url="https://example.com/x.jpg",
        display_mode="single",
    )
    session.add(img)
    draft.content_markdown = f"## 导语\n\n![image_asset_id={img.id}]\n\n尾段"
    await session.commit()
    await session.refresh(draft)
    await session.refresh(img)
    return draft, img, user


async def test_duplicate_conflict_leaves_no_orphan_images(session):
    """duplicate 到一个已存在的 new_id 会 409；事务回滚应保证不留新图片资产。"""
    src_draft, src_img, user = await _seed_draft_with_image(session)

    # 先占用 new_id
    occupied_id = str(ULID())
    session.add(
        Draft(
            id=occupied_id,
            event_id=src_draft.event_id,
            user_id=user.id,
            title="别人",
            angle_type="trend",
            outline_json=[],
            content_markdown="",
            status="editing",
            word_count=0,
            version=1,
        )
    )
    await session.commit()

    # 统计 image_assets 总数
    before = len(
        list(
            (await session.execute(select(ImageAsset.id))).scalars().all()
        )
    )

    with pytest.raises(Conflict):
        await DraftService(session).duplicate(
            src_id=src_draft.id,
            user_id=user.id,
            new_id=occupied_id,
            new_title="副本",
        )

    after = len(
        list(
            (await session.execute(select(ImageAsset.id))).scalars().all()
        )
    )
    assert before == after, "冲突路径不得留下新图片资产"
