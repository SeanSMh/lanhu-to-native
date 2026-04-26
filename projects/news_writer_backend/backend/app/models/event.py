from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_status_heat_score", "status", "heat_score"),
        Index("ix_events_status_updated_at", "status", "updated_at"),
        Index("ix_events_category_heat_score", "category", "heat_score"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline_json: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    keywords_json: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    suggested_angles_json: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    controversy_points_json: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    source_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    primary_news_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default=text("'active'"))
    cover_image_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    centroid_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
