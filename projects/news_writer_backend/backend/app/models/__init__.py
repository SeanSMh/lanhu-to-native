"""导入所有 model 以触发 Base.metadata 注册。

alembic env.py 会 `from app.models import *`，依赖本文件。
"""

from app.models.app_setting import AppSetting
from app.models.article import Article
from app.models.draft import Draft
from app.models.draft_version import DraftVersion
from app.models.event import Event
from app.models.event_news_item import EventNewsItem
from app.models.image_asset import ImageAsset
from app.models.llm_job import LlmJob
from app.models.news_item import NewsItem
from app.models.news_source import NewsSource
from app.models.style_profile import StyleProfile
from app.models.user import User

__all__ = [
    "AppSetting",
    "Article",
    "Draft",
    "DraftVersion",
    "Event",
    "EventNewsItem",
    "ImageAsset",
    "LlmJob",
    "NewsItem",
    "NewsSource",
    "StyleProfile",
    "User",
]
