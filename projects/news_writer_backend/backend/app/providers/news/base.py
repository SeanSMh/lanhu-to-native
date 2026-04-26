"""NewsSource 接口：可插拔的新闻源适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class NewsItemDraft:
    """一条抓取到的新闻（尚未入库）。"""

    title: str
    url: str
    description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    category: str | None = None
    language: str = "zh"
    raw_payload: dict = field(default_factory=dict)


class NewsSource(Protocol):
    name: str
    category: str

    async def fetch(self) -> list[NewsItemDraft]:
        ...
