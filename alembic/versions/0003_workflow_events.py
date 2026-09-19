"""Add workflow_events table and retry/drive fields to posts.

Revision ID: 0003_workflow_events
Revises: 0002_asmr_workflow
Create Date: 2026-09-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_workflow_events"
down_revision = "0002_asmr_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- workflow_events table ----
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="info"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_workflow_events_id", "workflow_events", ["id"])
    op.create_index("ix_workflow_events_post_id", "workflow_events", ["post_id"])
    op.create_index("ix_workflow_events_event_type", "workflow_events", ["event_type"])
    op.create_index("ix_workflow_events_created_at", "workflow_events", ["created_at"])

    # ---- Add new fields to posts ----
    # Google Drive archive
    op.add_column("posts", sa.Column("drive_file_id", sa.String(256), nullable=True))
    op.add_column(
        "posts",
        sa.Column("drive_upload_status", sa.String(32), nullable=False, server_default="none"),
    )
    op.create_index("ix_posts_drive_upload_status", "posts", ["drive_upload_status"])

    # Retry state
    op.add_column("posts", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("posts", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("posts", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("posts", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove retry/drive fields from posts
    op.drop_index("ix_posts_drive_upload_status", table_name="posts")
    op.drop_column("posts", "last_attempt_at")
    op.drop_column("posts", "last_error")
    op.drop_column("posts", "next_retry_at")
    op.drop_column("posts", "max_retries")
    op.drop_column("posts", "retry_count")
    op.drop_column("posts", "drive_upload_status")
    op.drop_column("posts", "drive_file_id")

    # Drop workflow_events table
    op.drop_index("ix_workflow_events_created_at", table_name="workflow_events")
    op.drop_index("ix_workflow_events_event_type", table_name="workflow_events")
    op.drop_index("ix_workflow_events_post_id", table_name="workflow_events")
    op.drop_index("ix_workflow_events_id", table_name="workflow_events")
    op.drop_table("workflow_events")
