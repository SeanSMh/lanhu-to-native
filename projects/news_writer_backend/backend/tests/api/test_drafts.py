from __future__ import annotations

import pytest
from httpx import AsyncClient
from ulid import ULID

from app.models.event import Event
from app.models.image_asset import ImageAsset
from tests.conftest import skip_if_no_db

pytestmark = [pytest.mark.asyncio, skip_if_no_db]


async def _seed_event(session) -> str:
    evt = Event(id=str(ULID()), title="e", category="tech", status="active")
    session.add(evt)
    await session.commit()
    return evt.id


async def _create_draft(client: AsyncClient, auth_header, event_id: str, **overrides):
    payload = {
        "id": str(ULID()),
        "event_id": event_id,
        "title": "标题",
        "angle_type": "trend",
        "outline": [],
        "content_markdown": "",
    }
    payload.update(overrides)
    r = await client.post("/api/v1/drafts", json=payload, headers=auth_header)
    return r, payload


async def test_create_draft_happy(client, auth_header, session):
    event_id = await _seed_event(session)
    r, payload = await _create_draft(client, auth_header, event_id)
    assert r.status_code == 201
    body = r.json()
    assert body["draft"]["id"] == payload["id"]
    assert body["draft"]["version"] == 1
    assert body["draft"]["status"] == "editing"


async def test_create_draft_event_missing(client, auth_header):
    r, _ = await _create_draft(client, auth_header, event_id="01NOPE000000000000000000X1")
    assert r.status_code == 404
    assert r.json()["code"] == "event_not_found"


async def test_create_draft_conflict_same_id(client, auth_header, session):
    event_id = await _seed_event(session)
    r1, payload = await _create_draft(client, auth_header, event_id)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/drafts", json=payload, headers=auth_header)
    assert r2.status_code == 409
    assert r2.json()["code"] == "conflict"


async def test_update_draft_increments_version(client, auth_header, session):
    event_id = await _seed_event(session)
    r, payload = await _create_draft(client, auth_header, event_id)
    draft_id = payload["id"]
    r2 = await client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={"base_version": 1, "title": "新标题", "content_markdown": "你好 hello world"},
        headers=auth_header,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["draft"]["title"] == "新标题"
    assert body["draft"]["version"] == 2
    assert body["draft"]["word_count"] == 2 + 2  # "你好" 2 汉字 + "hello"+"world"


async def test_update_draft_stale_version_409(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    draft_id = payload["id"]
    # 先 bump 到 2
    await client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={"base_version": 1, "title": "v2"},
        headers=auth_header,
    )
    # 再用陈旧 base_version
    r = await client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={"base_version": 1, "title": "v?"},
        headers=auth_header,
    )
    assert r.status_code == 409
    assert r.json()["code"] == "draft_version_conflict"
    assert r.json()["details"]["current_version"] == 2


async def test_update_draft_to_completed_rejected(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r = await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "status": "completed"},
        headers=auth_header,
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_snapshot_draft(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r = await client.post(
        f"/api/v1/drafts/{payload['id']}/snapshot",
        json={"reason": "before_format"},
        headers=auth_header,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["version"]["draft_id"] == payload["id"]
    assert body["version"]["version"] == 1
    assert body["version"]["reason"] == "before_format"


async def test_duplicate_draft_with_image_placeholder(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    draft_id = payload["id"]
    # 造一张 draft-scoped 图片
    image = ImageAsset(
        id=str(ULID()),
        owner_type="draft",
        owner_id=draft_id,
        source_type="search",
        image_url="https://example.com/i.jpg",
        thumb_url="https://example.com/i_t.jpg",
        width=1200,
        height=800,
        caption="示例",
        display_mode="single",
        provider_name="Pexels",
    )
    session.add(image)
    await session.commit()
    # 更新 draft 内容，加上占位符
    await client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={
            "base_version": 1,
            "content_markdown": f"## 导语\n\n![image_asset_id={image.id}]\n\n结束",
        },
        headers=auth_header,
    )
    # duplicate
    new_id = str(ULID())
    r = await client.post(
        f"/api/v1/drafts/{draft_id}/duplicate",
        json={"new_id": new_id, "new_title": "副本"},
        headers=auth_header,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["draft"]["id"] == new_id
    assert body["draft"]["version"] == 1
    # 新稿的 markdown 占位 id 应和原稿不同
    new_content = body["draft"]["content_markdown"]
    assert f"![image_asset_id={image.id}]" not in new_content
    assert "image_asset_id=" in new_content
    # referenced_images 中应包含新图
    assert len(body["draft"]["referenced_images"]) == 1


async def test_complete_empty_draft_rejected(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r = await client.post(
        f"/api/v1/drafts/{payload['id']}/complete", headers=auth_header
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_complete_happy_creates_article(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "content_markdown": "完整正文。"},
        headers=auth_header,
    )
    r = await client.post(
        f"/api/v1/drafts/{payload['id']}/complete", headers=auth_header
    )
    assert r.status_code == 200
    body = r.json()
    assert body["draft"]["status"] == "completed"
    assert body["article_id"]


async def test_complete_is_idempotent(client, auth_header, session):
    """重复 /complete 不得产生多条 article。"""
    from sqlalchemy import func, select

    from app.models.article import Article

    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "content_markdown": "完整正文。"},
        headers=auth_header,
    )
    r1 = await client.post(
        f"/api/v1/drafts/{payload['id']}/complete", headers=auth_header
    )
    assert r1.status_code == 200
    first_article = r1.json()["article_id"]

    for _ in range(2):
        rn = await client.post(
            f"/api/v1/drafts/{payload['id']}/complete", headers=auth_header
        )
        assert rn.status_code == 200
        assert rn.json()["article_id"] == first_article
        assert rn.json()["draft"]["status"] == "completed"

    cnt = (
        await session.execute(
            select(func.count(Article.id)).where(Article.draft_id == payload["id"])
        )
    ).scalar_one()
    assert cnt == 1


async def test_complete_archived_draft_rejected(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "status": "archived"},
        headers=auth_header,
    )
    r = await client.post(
        f"/api/v1/drafts/{payload['id']}/complete", headers=auth_header
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_create_draft_with_style_profile(client, auth_header, session):
    from app.models.style_profile import StyleProfile
    from sqlalchemy import select
    from app.models.user import User

    user = (await session.execute(select(User).limit(1))).scalar_one()
    profile = StyleProfile(
        id=str(ULID()),
        user_id=user.id,
        name="开发者视角",
        is_default=False,
    )
    session.add(profile)
    await session.commit()

    event_id = await _seed_event(session)
    payload = {
        "id": str(ULID()),
        "event_id": event_id,
        "title": "标题",
        "angle_type": "trend",
        "style_profile_id": profile.id,
        "outline": [],
        "content_markdown": "",
    }
    r = await client.post("/api/v1/drafts", json=payload, headers=auth_header)
    assert r.status_code == 201
    body = r.json()
    assert body["draft"]["style_profile_id"] == profile.id


async def test_create_draft_style_profile_not_found(client, auth_header, session):
    event_id = await _seed_event(session)
    payload = {
        "id": str(ULID()),
        "event_id": event_id,
        "title": "标题",
        "angle_type": "trend",
        "style_profile_id": "01NOSUCHSTYLE00000000000AA",
        "outline": [],
        "content_markdown": "",
    }
    r = await client.post("/api/v1/drafts", json=payload, headers=auth_header)
    assert r.status_code == 404
    assert r.json()["code"] == "style_profile_not_found"


async def test_update_draft_can_change_style_profile(client, auth_header, session):
    from app.models.style_profile import StyleProfile
    from sqlalchemy import select
    from app.models.user import User

    user = (await session.execute(select(User).limit(1))).scalar_one()
    profile = StyleProfile(
        id=str(ULID()),
        user_id=user.id,
        name="开发者视角",
        is_default=False,
    )
    session.add(profile)
    await session.commit()

    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r = await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "style_profile_id": profile.id},
        headers=auth_header,
    )
    assert r.status_code == 200
    assert r.json()["draft"]["style_profile_id"] == profile.id


async def test_empty_patch_does_not_bump_version(client, auth_header, session):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r = await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1},
        headers=auth_header,
    )
    assert r.status_code == 200
    assert r.json()["draft"]["version"] == 1  # 无变更不 +1


async def test_empty_patch_still_returns_409_on_stale_base_version(
    client, auth_header, session
):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    # 先推进到 v2
    await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1, "title": "v2"},
        headers=auth_header,
    )
    # 再拿陈旧 base_version=1 发空 patch
    r = await client.patch(
        f"/api/v1/drafts/{payload['id']}",
        json={"base_version": 1},
        headers=auth_header,
    )
    assert r.status_code == 409
    assert r.json()["code"] == "draft_version_conflict"


async def test_snapshot_twice_on_same_version_is_idempotent(
    client, auth_header, session
):
    event_id = await _seed_event(session)
    _, payload = await _create_draft(client, auth_header, event_id)
    r1 = await client.post(
        f"/api/v1/drafts/{payload['id']}/snapshot",
        json={"reason": "before_format"},
        headers=auth_header,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/drafts/{payload['id']}/snapshot",
        json={"reason": "before_format_again"},
        headers=auth_header,
    )
    # 不是 500，而是返回第一次的 version 对象
    assert r2.status_code == 201
    assert r2.json()["version"]["id"] == r1.json()["version"]["id"]
    assert r2.json()["version"]["version"] == 1


async def test_list_drafts_excludes_archived(client, auth_header, session):
    event_id = await _seed_event(session)
    _, a = await _create_draft(client, auth_header, event_id)
    _, b = await _create_draft(client, auth_header, event_id)
    # 归档 a
    await client.patch(
        f"/api/v1/drafts/{a['id']}",
        json={"base_version": 1, "status": "archived"},
        headers=auth_header,
    )
    r = await client.get("/api/v1/drafts", headers=auth_header)
    assert r.status_code == 200
    ids = [it["id"] for it in r.json()["items"]]
    assert b["id"] in ids
    assert a["id"] not in ids
