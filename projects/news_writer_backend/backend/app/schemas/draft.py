from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OutlineSection(BaseModel):
    section_key: str
    title: str
    goal: str


class ReferencedImage(BaseModel):
    image_asset_id: str
    image_url: str | None = None
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    display_mode: str = "single"
    source_type: str | None = None
    provider_name: str | None = None


class DraftDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    title: str | None
    angle_type: str | None
    style_profile_id: str | None = None
    outline: list[OutlineSection] = Field(default_factory=list)
    content_markdown: str
    formatted_content_markdown: str | None = None
    status: str
    word_count: int
    version: int
    created_at: datetime
    updated_at: datetime
    referenced_images: list[ReferencedImage] = Field(default_factory=list)


class DraftSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    title: str | None
    angle_type: str | None
    status: str
    word_count: int
    updated_at: datetime


class DraftCreate(BaseModel):
    id: str = Field(min_length=26, max_length=26)
    event_id: str
    title: str | None = None
    angle_type: str
    style_profile_id: str | None = None
    outline: list[OutlineSection] = Field(default_factory=list)
    content_markdown: str = ""


class DraftUpdate(BaseModel):
    base_version: int
    title: str | None = None
    style_profile_id: str | None = None
    outline: list[OutlineSection] | None = None
    content_markdown: str | None = None
    formatted_content_markdown: str | None = None
    status: Literal["editing", "archived"] | None = None


class DraftSnapshotCreate(BaseModel):
    reason: str | None = None


class DraftDuplicate(BaseModel):
    new_id: str = Field(min_length=26, max_length=26)
    new_title: str | None = None


class DraftListResponse(BaseModel):
    items: list[DraftSummary]
    next_cursor: str | None = None


class DraftDetailResponse(BaseModel):
    draft: DraftDetail


class DraftVersionOut(BaseModel):
    id: str
    draft_id: str
    version: int
    reason: str | None = None
    created_at: datetime


class DraftSnapshotResponse(BaseModel):
    version: DraftVersionOut


class DraftCompleteResponse(BaseModel):
    draft: DraftDetail
    article_id: str
