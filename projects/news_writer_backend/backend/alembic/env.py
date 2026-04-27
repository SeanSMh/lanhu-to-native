"""Alembic 入口：用同步驱动做迁移；运行时 app 用 async 驱动。"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.models import *  # noqa: F401,F403  触发全部 model 注册

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 把 async 驱动替换为同步（asyncpg → psycopg2）
sync_db_url = settings.db_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
