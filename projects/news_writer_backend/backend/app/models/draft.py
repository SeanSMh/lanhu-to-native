from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        Index("ix_drafts_user_status_updated", "user_id", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(26), ForeignKey("events.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    angle_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    outline_json: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    content_markdown: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    formatted_content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="editing", server_default=text("'editing'")
    )
    word_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    style_profile_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
