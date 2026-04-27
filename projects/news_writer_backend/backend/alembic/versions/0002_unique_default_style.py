"""enforce single default style_profile per user via partial unique index

Revision ID: 0002_unique_default_style
Revises: 0001_initial
Create Date: 2026-04-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_unique_default_style"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 落地前若表中已有同一 user_id 下多条 is_default=true，此处会创建失败；
    # 自用场景目前最多一条，无需数据清洗。若失败请手动修正再重跑。
    op.create_index(
        "uq_style_profiles_user_default_true",
        "style_profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_style_profiles_user_default_true",
        table_name="style_profiles",
    )
