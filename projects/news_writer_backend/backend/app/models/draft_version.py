from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (
        UniqueConstraint("draft_id", "version", name="uq_draft_versions_draft_version"),
        Index("ix_draft_versions_draft_version", "draft_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snapshot_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snapshot_outline_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    snapshot_content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
