"""RSS / Atom 适配器：用 httpx 抓取 + feedparser 解析。"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.core.errors import NewsSourceFailed
from app.providers.news.base import NewsItemDraft


def _parse_dt(entry: dict) -> datetime | None:
    # feedparser 标准化字段：published_parsed / updated_parsed 是 time.struct_time
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value is not None:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    # fallback 字符串
    for key in ("published", "updated", "pubDate"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                continue
    return None


def _pick_image(entry: dict) -> str | None:
    media = entry.get("media_content")
    if isinstance(media, list) and media:
        url = media[0].get("url")
        if url:
            return url
    thumb = entry.get("media_thumbnail")
    if isinstance(thumb, list) and thumb:
        url = thumb[0].get("url")
        if url:
            return url
    enclosures = entry.get("enclosures")
    if isinstance(enclosures, list) and enclosures:
        for enc in enclosures:
            mime = enc.get("type") or ""
            if mime.startswith("image"):
                return enc.get("url") or enc.get("href")
    return None


class RSSNewsSource:
    def __init__(self, *, name: str, base_url: str, category: str, timeout_s: float = 10.0):
        self.name = name
        self.base_url = base_url
        self.category = category
        self.timeout_s = timeout_s

    async def fetch(self) -> list[NewsItemDraft]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
                resp = await client.get(
                    self.base_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 news_writer/0.1 (+https://github.com/) "
                            "python-feedparser"
                        )
                    },
                )
        except httpx.HTTPError as e:
            raise NewsSourceFailed(
                f"{self.name} 抓取失败", {"url": self.base_url, "error": str(e)[:120]}
            ) from e
        if resp.status_code >= 400:
            raise NewsSourceFailed(
                f"{self.name} HTTP {resp.status_code}",
                {"url": self.base_url, "status": resp.status_code},
            )
        parsed = feedparser.parse(resp.content)
        items: list[NewsItemDraft] = []
        for entry in parsed.entries[:50]:  # 单源 50 上限，避免超大 feed
            url = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not url or not title:
                continue
            items.append(
                NewsItemDraft(
                    title=title[:500],
                    url=url[:1000],
                    description=((entry.get("summary") or entry.get("description") or "")[:5000]) or None,
                    author=entry.get("author"),
                    published_at=_parse_dt(entry),
                    image_url=_pick_image(entry),
                    category=self.category,
                    raw_payload={"feed_id": entry.get("id") or url},
                )
            )
        return items
