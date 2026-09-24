"""Alembic env.py — uses our SQLAlchemy Base and DATABASE_URL from config."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add project root to path so we can import backend.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.database import Base, normalize_db_url  # noqa: E402
# Import ALL models so Base.metadata has the complete schema for autogenerate.
# Alembic only sees tables that are registered on Base before target_metadata is set.
from backend.models import (  # noqa: E402, F401
    Post, WorkflowEvent, FoodItem, ASMRWorkflowRun, ASMRContentJob,
    ASMRPublishedContent, PostIdempotencyRecord, Job, RefreshToken, AuditLog,
)
from backend.config import settings

config = context.config

# Override sqlalchemy.url from our settings
config.set_main_option("sqlalchemy.url", normalize_db_url(settings.database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
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
