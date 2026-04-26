"""ImageSearchProvider 抽象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ImageSearchResult:
    provider_name: str
    image_url: str
    thumb_url: str | None
    width: int | None
    height: int | None
    copyright_note: str | None = None
    caption: str | None = None


class ImageSearchProvider(Protocol):
    name: str

    async def search(self, keyword: str, *, limit: int = 12) -> list[ImageSearchResult]:
        ...
