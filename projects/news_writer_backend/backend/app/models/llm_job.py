from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmJob(Base):
    """结构化记录每次 LLM 调用，便于排查。"""

    __tablename__ = "llm_jobs"
    __table_args__ = (
        Index("ix_llm_jobs_job_type_created_at", "job_type", "created_at"),
        Index("ix_llm_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_template_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
