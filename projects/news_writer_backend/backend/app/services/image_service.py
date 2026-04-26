"""Images API service + 工具函数。

纯函数实现：
- image_slots:  按 \n\n 切段 + LLM 建议 + 规则兜底
- recommend:    两种模式（draft/paragraph_text、event）
- search:       Pexels 关键词搜
- attach:       不改 draft，新建 owner=draft 的图片资产（继承 source 字段）
- upload:       multipart 上传 → storage → 缩略图

也提供 clone_draft_images 给 DraftService.duplicate。
"""

from __future__ import annotations

import mimetypes
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.errors import (
    DraftNotFound,
    EventNotFound,
    ImageNotFound,
    ImageSearchFailed,
    ValidationFailed,
)
from app.models.draft import Draft
from app.models.event import Event
from app.models.event_news_item import EventNewsItem
from app.models.image_asset import ImageAsset
from app.models.news_item import NewsItem
from app.providers.image_search.pexels import PexelsImageSearch
from app.providers.storage.router import get_storage
from app.schemas.image import (
    AttachedImageAsset,
    ImageCandidate,
    ImageSlot,
    UploadedImageAsset,
)
from app.services.llm_service import run_llm_job
from app.utils.image import get_size, make_thumbnail


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
VALID_OWNER_TYPES = {"event", "draft", "article", "library"}


# ---------- clone（给 DraftService.duplicate 用） ----------


async def clone_draft_images(
    session: AsyncSession, *, src_id: str, new_draft_id: str
) -> dict[str, str]:
    """拷贝原稿 draft-scoped 图片到新 draft，返回 old→new id 映射。

    ⚠️ 本函数**不 commit**，flush 后即返回；由调用方负责在同一事务里和新 draft
    一起 commit（DraftService.duplicate 依赖此语义保证原子性）。
    """
    rows = list(
        (
            await session.execute(
                select(ImageAsset).where(
                    ImageAsset.owner_type == "draft", ImageAsset.owner_id == src_id
                )
            )
        )
        .scalars()
        .all()
    )
    mapping: dict[str, str] = {}
    for src in rows:
        new_id = str(ULID())
        session.add(
            ImageAsset(
                id=new_id,
                owner_type="draft",
                owner_id=new_draft_id,
                source_type=src.source_type,
                image_url=src.image_url,
                thumb_url=src.thumb_url,
                storage_key=src.storage_key,
                width=src.width,
                height=src.height,
                caption=src.caption,
                display_mode=src.display_mode,
                provider_name=src.provider_name,
                copyright_note=src.copyright_note,
                source_image_id=src.id,
                metadata_json=dict(src.metadata_json or {}),
            )
        )
        mapping[src.id] = new_id
    if mapping:
        await session.flush()
    return mapping


# ---------- image-slots ----------


def _split_paragraphs(content: str) -> list[str]:
    return [p.strip() for p in (content or "").split("\n\n") if p.strip()]


async def image_slots_for_draft(session: AsyncSession, draft_id: str) -> list[ImageSlot]:
    draft = (
        await session.execute(select(Draft).where(Draft.id == draft_id))
    ).scalar_one_or_none()
    if draft is None:
        raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
    paragraphs = _split_paragraphs(draft.content_markdown or "")
    if not paragraphs:
        return []
    try:
        llm = await run_llm_job(
            session,
            job_type="image_slot_recommendation",
            prompt_template_id="image_slot_recommendation",
            variables={"paragraphs_json": paragraphs},
        )
        llm_slots = llm.get("slots") or []
    except Exception:
        llm_slots = []

    by_idx: dict[int, dict] = {}
    for s in llm_slots:
        if isinstance(s, dict) and isinstance(s.get("paragraph_index"), int):
            by_idx[s["paragraph_index"]] = s

    out: list[ImageSlot] = []
    for i, para in enumerate(paragraphs):
        suggested = "none"
        reason = "常规叙述段落"
        llm_hit = by_idx.get(i)
        if llm_hit and llm_hit.get("suggested_type") in (
            "hero", "product", "person", "timeline", "comparison", "none"
        ):
            suggested = llm_hit["suggested_type"]
            reason = (llm_hit.get("reason") or reason)[:40]
        else:
            # 规则兜底：首段 hero、含"发布/产品"建议 product
            if i == 0 or para.startswith("## 导语"):
                suggested = "hero"
                reason = "导语后主视觉定调"
            elif re.search(r"发布|产品|功能|截图", para):
                suggested = "product"
                reason = "段落涉及具体产品"
        out.append(
            ImageSlot(
                paragraph_index=i,
                paragraph_preview=para[:60],
                suggested_type=suggested,  # type: ignore[arg-type]
                reason=reason,
            )
        )
    return out


# ---------- search ----------


async def search_images(
    session: AsyncSession, *, keyword: str, limit: int
) -> list[ImageCandidate]:
    results = await PexelsImageSearch().search(keyword, limit=limit)
    candidates: list[ImageCandidate] = []
    for r in results:
        asset_id = str(ULID())
        session.add(
            ImageAsset(
                id=asset_id,
                owner_type="library",
                owner_id=None,
                source_type="search",
                image_url=r.image_url,
                thumb_url=r.thumb_url,
                width=r.width,
                height=r.height,
                caption=r.caption,
                display_mode="single",
                provider_name=r.provider_name,
                copyright_note=r.copyright_note,
                metadata_json={},
            )
        )
        candidates.append(
            ImageCandidate(
                image_asset_id=asset_id,
                image_url=r.image_url,
                thumb_url=r.thumb_url,
                source_type="search",
                provider_name=r.provider_name,
                copyright_note=r.copyright_note,
                width=r.width,
                height=r.height,
                caption=r.caption,
            )
        )
    await session.commit()
    return candidates


# ---------- recommend ----------


# preferred_type → Pexels 可用的英文补语。none / 未知类型留空。
_PREFERRED_TYPE_HINTS = {
    "hero": "cover",
    "product": "product",
    "person": "portrait",
    "timeline": "timeline",
    "comparison": "chart",
}


async def recommend_images(
    session: AsyncSession,
    *,
    draft_id: str | None,
    paragraph_text: str | None,
    event_id: str | None,
    preferred_type: str | None,
) -> list[ImageCandidate]:
    """模式互斥 + 完整性校验（与 RecommendRequest.validator 语义对齐）。

    - 段落模式字段（draft_id / paragraph_text）与事件模式字段（event_id）不得混用
    - 段落模式下 draft_id + paragraph_text 必须都出现

    schema 层已拦住正常路径；service 层保留防御性校验，方便直接调 service 的脚本/测试。
    """
    has_draft_id = bool((draft_id or "").strip())
    has_paragraph_text = bool((paragraph_text or "").strip())
    has_event_id = bool((event_id or "").strip())
    paragraph_fields = has_draft_id or has_paragraph_text
    event_fields = has_event_id

    if paragraph_fields and event_fields:
        raise ValidationFailed(
            "draft 模式与 event 模式字段不得混用",
            {
                "draft_id_present": has_draft_id,
                "paragraph_text_present": has_paragraph_text,
                "event_id_present": has_event_id,
            },
        )
    if paragraph_fields:
        if not (has_draft_id and has_paragraph_text):
            raise ValidationFailed(
                "段落模式需同时提供 draft_id 和 paragraph_text",
                {
                    "draft_id_present": has_draft_id,
                    "paragraph_text_present": has_paragraph_text,
                },
            )
        return await _recommend_from_paragraph(
            session,
            draft_id=draft_id,  # type: ignore[arg-type]
            paragraph_text=(paragraph_text or "")[:2000],
            preferred_type=preferred_type,
        )
    if event_fields:
        return await _recommend_from_event(
            session,
            event_id=event_id,  # type: ignore[arg-type]
            preferred_type=preferred_type,
        )
    raise ValidationFailed(
        "需提供 (draft_id + paragraph_text) 或 event_id",
        {"draft_id": draft_id, "paragraph_text_present": has_paragraph_text, "event_id": event_id},
    )


async def _recommend_from_paragraph(
    session: AsyncSession,
    *,
    draft_id: str,
    paragraph_text: str,
    preferred_type: str | None,
) -> list[ImageCandidate]:
    draft = (
        await session.execute(select(Draft).where(Draft.id == draft_id))
    ).scalar_one_or_none()
    if draft is None:
        raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
    keyword = _build_search_keyword(
        paragraph_text, fallback=draft.title or "", preferred_type=preferred_type
    )
    return await search_images(session, keyword=keyword, limit=12)


async def _recommend_from_event(
    session: AsyncSession,
    *,
    event_id: str,
    preferred_type: str | None,
) -> list[ImageCandidate]:
    evt = (
        await session.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if evt is None:
        raise EventNotFound("事件不存在", {"event_id": event_id})
    rows = list(
        (
            await session.execute(
                select(NewsItem)
                .join(EventNewsItem, EventNewsItem.news_item_id == NewsItem.id)
                .where(EventNewsItem.event_id == event_id, NewsItem.image_url.is_not(None))
                .order_by(NewsItem.published_at.desc().nullslast())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    candidates: list[ImageCandidate] = []
    # preferred_type=hero 且事件有封面 → 封面作为首个候选
    if preferred_type == "hero" and evt.cover_image_id:
        cover = (
            await session.execute(
                select(ImageAsset).where(ImageAsset.id == evt.cover_image_id)
            )
        ).scalar_one_or_none()
        if cover is not None:
            candidates.append(
                ImageCandidate(
                    image_asset_id=cover.id,
                    image_url=cover.image_url,
                    thumb_url=cover.thumb_url,
                    source_type=cover.source_type,
                    provider_name=cover.provider_name,
                    copyright_note=cover.copyright_note,
                    width=cover.width,
                    height=cover.height,
                    caption=cover.caption,
                )
            )
    for item in rows:
        asset_id = str(ULID())
        session.add(
            ImageAsset(
                id=asset_id,
                owner_type="event",
                owner_id=event_id,
                source_type="news",
                image_url=item.image_url,
                thumb_url=item.image_url,
                width=None,
                height=None,
                caption=item.title[:200],
                display_mode="single",
                provider_name=None,
                copyright_note=f"来源：新闻 {item.url}",
                metadata_json={"news_item_id": item.id},
            )
        )
        candidates.append(
            ImageCandidate(
                image_asset_id=asset_id,
                image_url=item.image_url,
                thumb_url=item.image_url,
                source_type="news",
                provider_name=None,
                copyright_note=f"来源：新闻 {item.url}",
                caption=item.title[:200],
            )
        )
    await session.commit()
    return candidates


def _build_search_keyword(
    paragraph: str, *, fallback: str, preferred_type: str | None
) -> str:
    base = _keyword_from_paragraph(paragraph, fallback=fallback)
    hint = _PREFERRED_TYPE_HINTS.get(preferred_type or "", "")
    if hint:
        return f"{base} {hint}".strip()
    return base


_STOP_WORDS = {"的", "了", "和", "是", "在", "也", "都", "有", "这", "那", "一个", "以及"}


def _keyword_from_paragraph(text: str, *, fallback: str) -> str:
    tokens = re.findall(r"[一-鿿A-Za-z]{2,10}", text)
    from collections import Counter

    cnt = Counter(t for t in tokens if t not in _STOP_WORDS)
    if not cnt:
        return fallback or text[:20]
    top = [w for w, _ in cnt.most_common(3)]
    return " ".join(top) or fallback or text[:20]


# ---------- attach ----------


async def attach_image(
    session: AsyncSession,
    *,
    draft_id: str,
    source_image_asset_id: str,
    caption: str | None,
    display_mode: str,
) -> AttachedImageAsset:
    draft = (
        await session.execute(select(Draft).where(Draft.id == draft_id))
    ).scalar_one_or_none()
    if draft is None:
        raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
    src = (
        await session.execute(
            select(ImageAsset).where(ImageAsset.id == source_image_asset_id)
        )
    ).scalar_one_or_none()
    if src is None:
        raise ImageNotFound("候选图不存在", {"image_asset_id": source_image_asset_id})
    new_id = str(ULID())
    new_asset = ImageAsset(
        id=new_id,
        owner_type="draft",
        owner_id=draft_id,
        source_type=src.source_type,
        image_url=src.image_url,
        thumb_url=src.thumb_url,
        storage_key=src.storage_key,
        width=src.width,
        height=src.height,
        caption=caption,
        display_mode=display_mode or "single",
        provider_name=src.provider_name,
        copyright_note=src.copyright_note,
        source_image_id=src.id,
        metadata_json=dict(src.metadata_json or {}),
    )
    session.add(new_asset)
    await session.commit()
    await session.refresh(new_asset)
    return AttachedImageAsset(
        image_asset_id=new_asset.id,
        image_url=new_asset.image_url,
        thumb_url=new_asset.thumb_url,
        source_type=new_asset.source_type,
        provider_name=new_asset.provider_name,
        width=new_asset.width,
        height=new_asset.height,
        caption=new_asset.caption,
        display_mode=new_asset.display_mode,  # type: ignore[arg-type]
    )


# ---------- upload ----------


async def _validate_owner(
    session: AsyncSession, owner_type: str, owner_id: str | None
) -> None:
    if owner_type not in VALID_OWNER_TYPES:
        raise ValidationFailed(
            "owner_type 不合法",
            {"owner_type": owner_type, "expected": sorted(VALID_OWNER_TYPES)},
        )
    if owner_type == "library":
        # library 不绑定具体实体，忽略 owner_id
        return
    if not owner_id:
        raise ValidationFailed(
            "owner_id 必填（owner_type != library）", {"owner_type": owner_type}
        )
    table_map = {"event": Event, "draft": Draft}
    # article 仅用于 complete 后的成稿快照；MVP 不直接 upload 到 article，简单允许存在性校验
    if owner_type == "article":
        from app.models.article import Article

        table_map["article"] = Article
    model = table_map[owner_type]
    exists = (
        await session.execute(select(model.id).where(model.id == owner_id))
    ).scalar_one_or_none()
    if exists is None:
        raise ValidationFailed(
            "owner 指向的实体不存在",
            {"owner_type": owner_type, "owner_id": owner_id},
        )


async def upload_image(
    session: AsyncSession,
    *,
    data: bytes,
    filename: str,
    owner_type: str,
    owner_id: str | None,
) -> UploadedImageAsset:
    await _validate_owner(session, owner_type, owner_id)
    # library 类型不绑定业务实体，强制丢弃任何外部传入的 owner_id，防止脏数据落库。
    if owner_type == "library":
        owner_id = None
    if len(data) == 0:
        raise ValidationFailed("文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationFailed("文件超过 10MB 上限", {"bytes": len(data)})
    mime, _ = mimetypes.guess_type(filename)
    if mime not in ALLOWED_MIME:
        raise ValidationFailed("仅支持 jpg/png/webp", {"mime": mime})

    try:
        width, height = get_size(data)
    except Exception as e:
        raise ValidationFailed("无法识别图像", {"error": str(e)[:120]})
    thumb_bytes, tw, th = make_thumbnail(data)

    storage = get_storage()
    new_id = str(ULID())
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    key = f"images/{new_id}.{ext}"
    thumb_key = f"images/{new_id}_thumb.jpg"
    image_url = await storage.put(key, data, content_type=mime)
    thumb_url = await storage.put(thumb_key, thumb_bytes, content_type="image/jpeg")

    asset = ImageAsset(
        id=new_id,
        owner_type=owner_type,
        owner_id=owner_id,
        source_type="upload",
        image_url=image_url,
        thumb_url=thumb_url,
        storage_key=key,
        width=width,
        height=height,
        display_mode="single",
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return UploadedImageAsset(
        image_asset_id=asset.id,
        image_url=asset.image_url,
        thumb_url=asset.thumb_url,
        source_type="upload",
        width=asset.width,
        height=asset.height,
    )
