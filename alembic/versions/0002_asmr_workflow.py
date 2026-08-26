"""add asmr workflow tables

Revision ID: 0002
Revises: 0001_initial
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_asmr_workflow"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # food_items
    op.create_table(
        "food_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("cycle_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_name", "cycle_number", name="uq_food_cycle"),
    )
    op.create_index("ix_food_items_normalized_name", "food_items", ["normalized_name"])

    # asmr_workflow_runs
    op.create_table(
        "asmr_workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("food_item_id", sa.Integer(), sa.ForeignKey("food_items.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asmr_workflow_runs_status", "asmr_workflow_runs", ["status"])

    # asmr_content_jobs
    op.create_table(
        "asmr_content_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("asmr_workflow_runs.id"), nullable=False),
        sa.Column("food_item_id", sa.Integer(), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("food_name", sa.String(128), nullable=False),
        sa.Column("video_prompt", sa.Text(), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.Text(), nullable=True),
        sa.Column("video_url", sa.String(512), nullable=True),
        sa.Column("video_storage_key", sa.String(512), nullable=True),
        sa.Column("video_size_bytes", sa.Integer(), nullable=True),
        sa.Column("video_mime_type", sa.String(64), nullable=True),
        sa.Column("video_duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asmr_content_jobs_workflow_run_id", "asmr_content_jobs", ["workflow_run_id"])

    # asmr_published_content
    op.create_table(
        "asmr_published_content",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_job_id", sa.Integer(), sa.ForeignKey("asmr_content_jobs.id"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("platform_post_id", sa.String(128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asmr_published_content_job_id", "asmr_published_content", ["content_job_id"])


def downgrade() -> None:
    op.drop_table("asmr_published_content")
    op.drop_table("asmr_content_jobs")
    op.drop_table("asmr_workflow_runs")
    op.drop_table("food_items")
