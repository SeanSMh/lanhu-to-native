from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StyleProfile(Base):
    __tablename__ = "style_profiles"
    __table_args__ = (
        Index("ix_style_profiles_user_default", "user_id", "is_default"),
        # 部分唯一索引：每个 user 最多一条 is_default=true，并发下由 DB 兜底。
        Index(
            "uq_style_profiles_user_default_true",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tone: Mapped[str | None] = mapped_column(String(500), nullable=True)
    forbidden_words_json: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    preferred_structure: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paragraph_style: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headline_style: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prompt_preset: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
