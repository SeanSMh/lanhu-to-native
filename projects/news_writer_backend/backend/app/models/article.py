from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(26), ForeignKey("drafts.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_platform: Mapped[str | None] = mapped_column(String(30), nullable=True)
    published_status: Mapped[str] = mapped_column(
        String(20), default="manual", server_default=text("'manual'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
