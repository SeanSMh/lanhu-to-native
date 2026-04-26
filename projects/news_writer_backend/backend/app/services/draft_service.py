"""Drafts API service：创建 / 查询 / 更新（乐观锁） / 快照 / 复制 / 完成。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.errors import (
    Conflict,
    DraftNotFound,
    EventNotFound,
    StyleProfileNotFound,
    ValidationFailed,
)
from app.models.article import Article
from app.models.draft import Draft
from app.models.draft_version import DraftVersion
from app.models.event import Event
from app.models.image_asset import ImageAsset
from app.models.style_profile import StyleProfile
from app.repositories.draft_repository import DraftRepository
from app.schemas.draft import (
    DraftCreate,
    DraftDetail,
    DraftSummary,
    DraftUpdate,
    DraftVersionOut,
    OutlineSection,
    ReferencedImage,
)

IMAGE_REF_RE = re.compile(r"!\[image_asset_id=(01[A-Z0-9]{24})\]")


def _count_words(text: str | None) -> int:
    """中文 + 英文混合的轻量字数：中文按字符数，英文按 \\b 单词数。"""
    if not text:
        return 0
    cleaned = IMAGE_REF_RE.sub("", text)
    chinese = sum(1 for c in cleaned if "一" <= c <= "鿿")
    english = len(re.findall(r"[A-Za-z]+", cleaned))
    return chinese + english


class DraftService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DraftRepository(session)

    # ---------- 转换 ----------

    def _outline_as_dicts(self, outline: list[OutlineSection] | list[dict]) -> list[dict]:
        out: list[dict] = []
        for s in outline:
            if isinstance(s, dict):
                out.append({"section_key": s["section_key"], "title": s["title"], "goal": s["goal"]})
            else:
                out.append(s.model_dump())
        return out

    async def _referenced_images(self, draft: Draft) -> list[ReferencedImage]:
        ids: list[str] = []
        seen: set[str] = set()
        for text in (draft.content_markdown, draft.formatted_content_markdown or ""):
            for m in IMAGE_REF_RE.findall(text or ""):
                if m not in seen:
                    seen.add(m)
                    ids.append(m)
        if not ids:
            return []
        rows = list(
            (
                await self.session.execute(
                    select(ImageAsset).where(ImageAsset.id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        by_id = {a.id: a for a in rows}
        refs: list[ReferencedImage] = []
        for i in ids:
            a = by_id.get(i)
            if a is None:
                continue
            refs.append(
                ReferencedImage(
                    image_asset_id=a.id,
                    image_url=a.image_url,
                    thumb_url=a.thumb_url,
                    width=a.width,
                    height=a.height,
                    caption=a.caption,
                    display_mode=a.display_mode or "single",
                    source_type=a.source_type,
                    provider_name=a.provider_name,
                )
            )
        return refs

    async def _to_detail(self, draft: Draft) -> DraftDetail:
        outline = [
            OutlineSection(**s) for s in (draft.outline_json or []) if isinstance(s, dict)
        ]
        return DraftDetail(
            id=draft.id,
            event_id=draft.event_id,
            title=draft.title,
            angle_type=draft.angle_type,
            style_profile_id=draft.style_profile_id,
            outline=outline,
            content_markdown=draft.content_markdown or "",
            formatted_content_markdown=draft.formatted_content_markdown,
            status=draft.status,
            word_count=draft.word_count or 0,
            version=draft.version or 1,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            referenced_images=await self._referenced_images(draft),
        )

    async def _ensure_style_profile(self, user_id: str, profile_id: str) -> None:
        found = (
            await self.session.execute(
                select(StyleProfile.id).where(
                    StyleProfile.id == profile_id, StyleProfile.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise StyleProfileNotFound(
                "风格配置不存在", {"style_profile_id": profile_id}
            )

    # ---------- 用例 ----------

    async def create(self, user_id: str, payload: DraftCreate) -> DraftDetail:
        evt = (
            await self.session.execute(select(Event.id).where(Event.id == payload.event_id))
        ).scalar_one_or_none()
        if evt is None:
            raise EventNotFound("事件不存在", {"event_id": payload.event_id})
        if await self.repo.get(payload.id) is not None:
            raise Conflict("草稿 id 已存在", {"id": payload.id})
        if payload.style_profile_id is not None:
            await self._ensure_style_profile(user_id, payload.style_profile_id)
        draft = Draft(
            id=payload.id,
            event_id=payload.event_id,
            user_id=user_id,
            title=payload.title,
            angle_type=payload.angle_type,
            style_profile_id=payload.style_profile_id,
            outline_json=self._outline_as_dicts(payload.outline),
            content_markdown=payload.content_markdown or "",
            status="editing",
            word_count=_count_words(payload.content_markdown),
            version=1,
        )
        await self.repo.add(draft)
        return await self._to_detail(draft)

    async def list(
        self, user_id: str, status: str | None, cursor: str | None, limit: int
    ) -> tuple[list[DraftSummary], str | None]:
        rows, next_cursor = await self.repo.list_for_user(
            user_id, status=status, cursor=cursor, limit=limit
        )
        items = [
            DraftSummary(
                id=r.id,
                event_id=r.event_id,
                title=r.title,
                angle_type=r.angle_type,
                status=r.status,
                word_count=r.word_count or 0,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
        return items, next_cursor

    async def get_detail(self, draft_id: str) -> DraftDetail:
        draft = await self.repo.get(draft_id)
        if draft is None:
            raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
        return await self._to_detail(draft)

    async def update(
        self, draft_id: str, user_id: str, payload: DraftUpdate
    ) -> DraftDetail:
        patch: dict[str, Any] = {}
        data = payload.model_dump(exclude_unset=True)
        base_version = data.pop("base_version")
        if "status" in data and data["status"] not in ("editing", "archived"):
            raise ValidationFailed("status 只能切换到 editing / archived")
        if "title" in data:
            patch["title"] = data["title"]
        if "style_profile_id" in data:
            if data["style_profile_id"] is not None:
                await self._ensure_style_profile(user_id, data["style_profile_id"])
            patch["style_profile_id"] = data["style_profile_id"]
        if "outline" in data and data["outline"] is not None:
            patch["outline_json"] = self._outline_as_dicts(data["outline"])
        if "content_markdown" in data and data["content_markdown"] is not None:
            patch["content_markdown"] = data["content_markdown"]
            patch["word_count"] = _count_words(data["content_markdown"])
        if "formatted_content_markdown" in data:
            patch["formatted_content_markdown"] = data["formatted_content_markdown"]
        if "status" in data and data["status"] is not None:
            patch["status"] = data["status"]
        if not patch:
            # 空 patch：仍然校验 base_version，但不推进 version，原样返回。
            # 避免空 autosave 在 version 上制造噪音、放大真实编辑的 409 概率。
            current = await self.repo.get(draft_id)
            if current is None:
                raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
            if current.version != base_version:
                from app.core.errors import DraftVersionConflict

                raise DraftVersionConflict(
                    "草稿已被其它操作更新，请刷新后重试",
                    {"current_version": current.version, "base_version": base_version},
                )
            return await self._to_detail(current)
        updated = await self.repo.update_with_version(draft_id, base_version, patch)
        return await self._to_detail(updated)

    async def snapshot(self, draft_id: str, reason: str | None) -> DraftVersionOut:
        """为当前草稿版本创建快照；同一 (draft_id, version) 幂等。

        用户连点"一键排版前快照"两次（中间无 PATCH），第二次直接返回第一次的版本，
        不抛唯一约束异常、不变造新版本。
        """
        draft = await self.repo.get(draft_id)
        if draft is None:
            raise DraftNotFound("草稿不存在", {"draft_id": draft_id})

        existing = (
            await self.session.execute(
                select(DraftVersion).where(
                    DraftVersion.draft_id == draft.id,
                    DraftVersion.version == draft.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return DraftVersionOut(
                id=existing.id,
                draft_id=draft.id,
                version=existing.version,
                reason=existing.reason,
                created_at=existing.created_at,
            )

        v = DraftVersion(
            id=str(ULID()),
            draft_id=draft.id,
            version=draft.version,
            reason=reason,
            snapshot_title=draft.title,
            snapshot_outline_json=draft.outline_json,
            snapshot_content_markdown=draft.content_markdown,
        )
        self.session.add(v)
        try:
            await self.session.commit()
        except IntegrityError:
            # 并发下另一个请求先写成功，rollback 后重新读一次返回。
            await self.session.rollback()
            racer = (
                await self.session.execute(
                    select(DraftVersion).where(
                        DraftVersion.draft_id == draft.id,
                        DraftVersion.version == draft.version,
                    )
                )
            ).scalar_one()
            return DraftVersionOut(
                id=racer.id,
                draft_id=draft.id,
                version=racer.version,
                reason=racer.reason,
                created_at=racer.created_at,
            )
        await self.session.refresh(v)
        return DraftVersionOut(
            id=v.id,
            draft_id=draft.id,
            version=v.version,
            reason=v.reason,
            created_at=v.created_at,
        )

    async def duplicate(
        self, src_id: str, user_id: str, new_id: str, new_title: str | None
    ) -> DraftDetail:
        src = await self.repo.get(src_id)
        if src is None:
            raise DraftNotFound("原稿不存在", {"draft_id": src_id})
        if await self.repo.get(new_id) is not None:
            raise Conflict("新草稿 id 已存在", {"new_id": new_id})

        # 深拷贝 draft-scoped image_assets 和新 draft 必须在同一事务里一次性提交，
        # 否则任一步失败就会留下 owner 指向不存在 draft 的孤儿图片资产。
        from app.services.image_service import clone_draft_images

        try:
            id_map = await clone_draft_images(
                self.session, src_id=src_id, new_draft_id=new_id
            )
            new_content = src.content_markdown or ""
            new_formatted = src.formatted_content_markdown or ""
            for old_id, new_img_id in id_map.items():
                new_content = new_content.replace(
                    f"![image_asset_id={old_id}]", f"![image_asset_id={new_img_id}]"
                )
                new_formatted = new_formatted.replace(
                    f"![image_asset_id={old_id}]", f"![image_asset_id={new_img_id}]"
                )

            cloned = Draft(
                id=new_id,
                event_id=src.event_id,
                user_id=user_id,
                title=new_title or (f"{src.title or ''}（副本）" if src.title else "（副本）"),
                angle_type=src.angle_type,
                style_profile_id=src.style_profile_id,
                outline_json=list(src.outline_json or []),
                content_markdown=new_content,
                formatted_content_markdown=new_formatted or None,
                status="editing",
                word_count=_count_words(new_content),
                version=1,
            )
            self.session.add(cloned)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(cloned)
        return await self._to_detail(cloned)

    async def complete(self, draft_id: str, user_id: str) -> tuple[DraftDetail, str]:
        """草稿 → 成稿，幂等。

        - 状态 `editing`：校验非空 → 原子 CAS `editing → completed` → 建 article
        - 状态 `completed`：直接返回已有第一条 article（网络重试/连点场景幂等）
        - 状态 `archived`：422
        - 不存在：404

        原子流转：用 `UPDATE ... WHERE status='editing' RETURNING id`，并发下只会有一个
        请求赢得流转并建 article，其它请求走幂等分支读已有 article。
        """
        draft = await self.repo.get(draft_id)
        if draft is None:
            raise DraftNotFound("草稿不存在", {"draft_id": draft_id})

        # 幂等路径
        if draft.status == "completed":
            existing_id = await self._existing_article_id(draft.id)
            if existing_id is None:
                # 理论上不应出现；防御性重建一条（例如历史脏数据）
                existing_id = await self._insert_article(draft, user_id)
                await self.session.commit()
            return await self._to_detail(draft), existing_id

        if draft.status != "editing":
            raise ValidationFailed(
                f"当前状态 {draft.status} 不允许完成", {"status": draft.status}
            )
        if not draft.title or not (draft.content_markdown or "").strip():
            raise ValidationFailed("草稿标题或内容为空，无法完成")

        # 原子 CAS：只在 status='editing' 时翻转到 'completed'
        from sqlalchemy import update as sa_update

        won = (
            await self.session.execute(
                sa_update(Draft)
                .where(Draft.id == draft_id, Draft.status == "editing")
                .values(status="completed")
                .returning(Draft.id)
            )
        ).scalar_one_or_none()

        if won is None:
            # 被并发者抢先翻转到 completed；走幂等分支
            await self.session.rollback()
            draft = await self.repo.get(draft_id)
            if draft is None:
                raise DraftNotFound("草稿不存在", {"draft_id": draft_id})
            if draft.status == "completed":
                existing_id = await self._existing_article_id(draft.id)
                if existing_id is not None:
                    return await self._to_detail(draft), existing_id
            raise ValidationFailed(
                f"状态流转失败：{draft.status}", {"status": draft.status}
            )

        # 本次拿到所有权，负责建 article
        article_id = await self._insert_article(draft, user_id)
        await self.session.commit()
        draft = await self.repo.get(draft_id)
        return await self._to_detail(draft), article_id

    async def _existing_article_id(self, draft_id: str) -> str | None:
        return (
            await self.session.execute(
                select(Article.id)
                .where(Article.draft_id == draft_id)
                .order_by(Article.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _insert_article(self, draft: Draft, user_id: str) -> str:
        article_id = str(ULID())
        self.session.add(
            Article(
                id=article_id,
                draft_id=draft.id,
                user_id=user_id,
                title=draft.title,
                content_markdown=draft.content_markdown,
                published_platform=None,
                published_status="manual",
            )
        )
        return article_id
