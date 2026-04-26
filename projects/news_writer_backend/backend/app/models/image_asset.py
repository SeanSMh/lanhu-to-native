from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImageAsset(Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        Index("ix_image_assets_owner", "owner_type", "owner_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    owner_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumb_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_mode: Mapped[str] = mapped_column(
        String(20), default="single", server_default=text("'single'")
    )
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    copyright_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_image_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
