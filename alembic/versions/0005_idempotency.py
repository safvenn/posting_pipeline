"""Add post_idempotency_records table.

Revision ID: 0005_idempotency
Revises: 0004_add_clean_drive_file_id
Create Date: 2026-09-24

Purpose:
    Adds the post_idempotency_records table to prevent duplicate
    YouTube uploads, Instagram publishes, Drive archives, and Sheet
    updates after worker crashes, network timeouts, or process restarts.

    Key format examples stored in the `key` column:
      youtube:post:182:publish
      instagram:post:182:publish
      instagram:post:182:container_create
      sheet:post:182:update
      drive:post:182:archive_original
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_idempotency"
down_revision = "0004_add_clean_drive_file_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("external_id", sa.String(256), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_idempotency_key"),
    )
    # Index for fast key lookup (most frequent operation)
    op.create_index(
        "ix_post_idempotency_records_key",
        "post_idempotency_records",
        ["key"],
        unique=True,
    )
    # Index for status-based queries (e.g., maintenance cleanup)
    op.create_index(
        "ix_post_idempotency_records_status",
        "post_idempotency_records",
        ["status"],
    )
    # Index for TTL-based cleanup
    op.create_index(
        "ix_post_idempotency_records_expires_at",
        "post_idempotency_records",
        ["expires_at"],
    )

    # Also add missing composite indexes on posts table for queue queries
    # These dramatically improve job selection performance
    op.create_index(
        "ix_posts_status_created_at",
        "posts",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_posts_status_next_retry_at",
        "posts",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_posts_status_scheduled_at",
        "posts",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "ix_posts_channel_status",
        "posts",
        ["channel", "status"],
    )
    # Index for workflow_events post timeline queries
    op.create_index(
        "ix_workflow_events_post_id_created_at",
        "workflow_events",
        ["post_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_post_id_created_at", "workflow_events")
    op.drop_index("ix_posts_channel_status", "posts")
    op.drop_index("ix_posts_status_scheduled_at", "posts")
    op.drop_index("ix_posts_status_next_retry_at", "posts")
    op.drop_index("ix_posts_status_created_at", "posts")
    op.drop_index("ix_post_idempotency_records_expires_at", "post_idempotency_records")
    op.drop_index("ix_post_idempotency_records_status", "post_idempotency_records")
    op.drop_index("ix_post_idempotency_records_key", "post_idempotency_records")
    op.drop_table("post_idempotency_records")
