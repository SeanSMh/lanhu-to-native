from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventNewsItem(Base):
    __tablename__ = "event_news_items"
    __table_args__ = (
        UniqueConstraint("event_id", "news_item_id", name="uq_event_news_items_event_news"),
        Index("ix_event_news_items_event_id", "event_id"),
        Index("ix_event_news_items_news_item_id", "news_item_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    news_item_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
