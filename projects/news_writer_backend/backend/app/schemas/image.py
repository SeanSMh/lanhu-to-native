from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

DisplayMode = Literal["single", "caption_below"]
SuggestedType = Literal["hero", "product", "person", "timeline", "comparison", "none"]
OwnerType = Literal["event", "draft", "article", "library"]


class ImageSlot(BaseModel):
    paragraph_index: int
    paragraph_preview: str
    suggested_type: SuggestedType
    reason: str


class ImageSlotsResponse(BaseModel):
    slots: list[ImageSlot]


class ImageCandidate(BaseModel):
    image_asset_id: str
    image_url: str | None = None
    thumb_url: str | None = None
    source_type: str | None = None
    provider_name: str | None = None
    copyright_note: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None


class ImageCandidateListResponse(BaseModel):
    candidates: list[ImageCandidate]


class RecommendRequest(BaseModel):
    """两种模式二选一（api-contract §5.2）：

    - 段落模式：draft_id + paragraph_text 都必填
    - 事件模式：event_id 必填

    **字段级互斥**：段落模式字段（draft_id / paragraph_text）与事件模式字段（event_id）
    不得混用。例如 `{"event_id": ..., "draft_id": ...}` 或 `{"event_id": ..., "paragraph_text": ...}`
    也属于非法组参（客户端大概率是组参错误，而不是事件模式），一律 422。
    """

    draft_id: str | None = None
    paragraph_text: str | None = None
    event_id: str | None = None
    preferred_type: SuggestedType | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "RecommendRequest":
        has_draft_id = bool((self.draft_id or "").strip())
        has_paragraph_text = bool((self.paragraph_text or "").strip())
        has_event_id = bool((self.event_id or "").strip())

        paragraph_fields = has_draft_id or has_paragraph_text
        event_fields = has_event_id

        if paragraph_fields and event_fields:
            raise ValueError(
                "draft 模式与 event 模式字段不得混用，请只传其中一组"
            )
        if paragraph_fields:
            if not (has_draft_id and has_paragraph_text):
                raise ValueError(
                    "段落模式需同时提供 draft_id 和 paragraph_text"
                )
            return self
        if event_fields:
            return self
        raise ValueError("需提供 (draft_id + paragraph_text) 或 event_id")


class SearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=12, ge=1, le=30)


class AttachRequest(BaseModel):
    draft_id: str
    source_image_asset_id: str
    caption: str | None = None
    display_mode: DisplayMode = "single"


class AttachedImageAsset(BaseModel):
    image_asset_id: str
    image_url: str | None = None
    thumb_url: str | None = None
    source_type: str | None = None
    provider_name: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    display_mode: DisplayMode = "single"


class AttachResponse(BaseModel):
    image_asset: AttachedImageAsset


class UploadedImageAsset(BaseModel):
    image_asset_id: str
    image_url: str | None = None
    thumb_url: str | None = None
    source_type: str = "upload"
    width: int | None = None
    height: int | None = None


class UploadResponse(BaseModel):
    image_asset: UploadedImageAsset
