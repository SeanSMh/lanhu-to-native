from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SuggestedAngle(BaseModel):
    angle_type: str
    label: str
    one_liner: str


class TimelinePoint(BaseModel):
    time: datetime | str | None = None
    text: str


class CoverImage(BaseModel):
    image_asset_id: str
    thumb_url: str | None = None


class EventListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    summary: str | None = None
    category: str | None = None
    heat_score: float = 0.0
    source_count: int = 0
    updated_at: datetime
    suggested_angle: str | None = None


class EventListResponse(BaseModel):
    items: list[EventListItem]
    next_cursor: str | None = None


class EventDetail(BaseModel):
    id: str
    title: str
    summary: str | None = None
    category: str | None = None
    heat_score: float = 0.0
    source_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime
    timeline: list[TimelinePoint] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    suggested_angles: list[SuggestedAngle] = Field(default_factory=list)
    cover_image: CoverImage | None = None
    controversy_points: list[str] = Field(default_factory=list)


class EventNewsItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None = None
    url: str
    source_name: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None


class EventNewsListResponse(BaseModel):
    items: list[EventNewsItem]
    next_cursor: str | None = None


class EventsRefreshRequest(BaseModel):
    categories: list[str] | None = None


class EventsRefreshResponse(BaseModel):
    job_id: str
    accepted_at: datetime


EventSortField = Literal["heat", "latest"]
