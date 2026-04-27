"""initial schema: 12 张表

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("nickname", sa.String(length=100), nullable=False),
        sa.Column("api_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # news_sources
    op.create_table(
        "news_sources",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_fetched_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # news_items
    op.create_table(
        "news_items",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("source_id", sa.String(length=26), sa.ForeignKey("news_sources.id"), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False, unique=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=True),
        sa.Column("language", sa.String(length=10), server_default=sa.text("'zh'"), nullable=False),
        sa.Column("embedding_json", postgresql.JSONB(), nullable=True),
        sa.Column("embedded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_news_items_content_hash", "news_items", ["content_hash"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_category_published_at", "news_items", ["category", "published_at"])

    # events
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("timeline_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("keywords_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("suggested_angles_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("controversy_points_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=True),
        sa.Column("heat_score", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("primary_news_id", sa.String(length=26), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("cover_image_id", sa.String(length=26), nullable=True),
        sa.Column("centroid_embedding", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_events_status_heat_score", "events", ["status", "heat_score"])
    op.create_index("ix_events_status_updated_at", "events", ["status", "updated_at"])
    op.create_index("ix_events_category_heat_score", "events", ["category", "heat_score"])

    # event_news_items
    op.create_table(
        "event_news_items",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("event_id", sa.String(length=26), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("news_item_id", sa.String(length=26), sa.ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("event_id", "news_item_id", name="uq_event_news_items_event_news"),
    )
    op.create_index("ix_event_news_items_event_id", "event_news_items", ["event_id"])
    op.create_index("ix_event_news_items_news_item_id", "event_news_items", ["news_item_id"])

    # drafts
    op.create_table(
        "drafts",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("event_id", sa.String(length=26), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", sa.String(length=26), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("angle_type", sa.String(length=30), nullable=True),
        sa.Column("outline_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("content_markdown", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("formatted_content_markdown", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'editing'"), nullable=False),
        sa.Column("word_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("style_profile_id", sa.String(length=26), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_drafts_user_status_updated", "drafts", ["user_id", "status", "updated_at"])

    # draft_versions
    op.create_table(
        "draft_versions",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("draft_id", sa.String(length=26), sa.ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("snapshot_title", sa.String(length=500), nullable=True),
        sa.Column("snapshot_outline_json", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_content_markdown", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("draft_id", "version", name="uq_draft_versions_draft_version"),
    )
    op.create_index("ix_draft_versions_draft_version", "draft_versions", ["draft_id", "version"])

    # articles
    op.create_table(
        "articles",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("draft_id", sa.String(length=26), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("user_id", sa.String(length=26), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("published_platform", sa.String(length=30), nullable=True),
        sa.Column("published_status", sa.String(length=20), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # image_assets
    op.create_table(
        "image_assets",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("owner_type", sa.String(length=20), nullable=True),
        sa.Column("owner_id", sa.String(length=26), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("thumb_url", sa.String(length=1000), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("caption", sa.String(length=500), nullable=True),
        sa.Column("display_mode", sa.String(length=20), server_default=sa.text("'single'"), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=True),
        sa.Column("copyright_note", sa.String(length=500), nullable=True),
        sa.Column("source_image_id", sa.String(length=26), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_image_assets_owner", "image_assets", ["owner_type", "owner_id"])

    # style_profiles
    op.create_table(
        "style_profiles",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("user_id", sa.String(length=26), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("tone", sa.String(length=500), nullable=True),
        sa.Column("forbidden_words_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("preferred_structure", sa.String(length=500), nullable=True),
        sa.Column("paragraph_style", sa.String(length=500), nullable=True),
        sa.Column("headline_style", sa.String(length=500), nullable=True),
        sa.Column("prompt_preset", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_style_profiles_user_default", "style_profiles", ["user_id", "is_default"])

    # app_settings
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # llm_jobs
    op.create_table(
        "llm_jobs",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prompt_template_id", sa.String(length=50), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_llm_jobs_job_type_created_at", "llm_jobs", ["job_type", "created_at"])
    op.create_index("ix_llm_jobs_status_created_at", "llm_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_jobs_status_created_at", table_name="llm_jobs")
    op.drop_index("ix_llm_jobs_job_type_created_at", table_name="llm_jobs")
    op.drop_table("llm_jobs")
    op.drop_table("app_settings")
    op.drop_index("ix_style_profiles_user_default", table_name="style_profiles")
    op.drop_table("style_profiles")
    op.drop_index("ix_image_assets_owner", table_name="image_assets")
    op.drop_table("image_assets")
    op.drop_table("articles")
    op.drop_index("ix_draft_versions_draft_version", table_name="draft_versions")
    op.drop_table("draft_versions")
    op.drop_index("ix_drafts_user_status_updated", table_name="drafts")
    op.drop_table("drafts")
    op.drop_index("ix_event_news_items_news_item_id", table_name="event_news_items")
    op.drop_index("ix_event_news_items_event_id", table_name="event_news_items")
    op.drop_table("event_news_items")
    op.drop_index("ix_events_category_heat_score", table_name="events")
    op.drop_index("ix_events_status_updated_at", table_name="events")
    op.drop_index("ix_events_status_heat_score", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_news_items_category_published_at", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_content_hash", table_name="news_items")
    op.drop_table("news_items")
    op.drop_table("news_sources")
    op.drop_table("users")
