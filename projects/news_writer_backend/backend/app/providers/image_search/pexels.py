"""Pexels 搜图：https://www.pexels.com/api/ 。"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.errors import ImageSearchFailed
from app.providers.image_search.base import ImageSearchResult


class PexelsImageSearch:
    name = "Pexels"

    async def search(self, keyword: str, *, limit: int = 12) -> list[ImageSearchResult]:
        if not settings.image_search_api_key:
            raise ImageSearchFailed("IMAGE_SEARCH_API_KEY 未配置")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": keyword, "per_page": max(1, min(limit, 30)), "locale": "zh-CN"},
                    headers={"Authorization": settings.image_search_api_key},
                )
        except httpx.HTTPError as e:
            raise ImageSearchFailed("搜图网络错误", {"error": str(e)[:200]}) from e
        if resp.status_code >= 400:
            raise ImageSearchFailed(
                "搜图上游失败",
                {"status": resp.status_code, "body_preview": resp.text[:200]},
            )
        body = resp.json()
        photos = body.get("photos") or []
        out: list[ImageSearchResult] = []
        for p in photos:
            src = p.get("src") or {}
            out.append(
                ImageSearchResult(
                    provider_name=self.name,
                    image_url=src.get("large") or src.get("original") or "",
                    thumb_url=src.get("small") or src.get("medium"),
                    width=p.get("width"),
                    height=p.get("height"),
                    copyright_note=f"Photo by {p.get('photographer', 'Pexels')} on Pexels",
                    caption=(p.get("alt") or None),
                )
            )
        return out
