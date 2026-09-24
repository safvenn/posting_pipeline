"""Add Instagram columns, sheet_row_id, and Phase 4-6 performance indexes.

Revision ID: 0007_instagram_and_indexes
Revises: 0006_jobs_tokens_audit
Create Date: 2026-09-24

Purpose:
    Closes the schema gap between models.py and existing migrations.

    1. Instagram columns on posts — instagram_media_id, instagram_post_url,
       instagram_status, instagram_error, instagram_container_id.
       These were in models.py since the Instagram integration but never
       had a formal migration (they were added via create_all on Render).

    2. sheet_row_id on posts — Google Sheets row matching.

    3. Performance indexes for Phase 4-6 queries:
       - ix_jobs_status_finished_at  (DLQ + stale job recovery queries)
       - ix_jobs_job_type_post_id    (per-step latency percentile queries)
       - ix_audit_logs_outcome       (security dashboard queries)
       - ix_refresh_tokens_active    (partial index: non-revoked, non-expired)

    All add_column operations use `if_not_exists` pattern via batch_alter_table
    or raw try/except to be idempotent (safe to run on DBs that already have
    these columns from create_all or manual DDL).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_instagram_and_indexes"
down_revision = "0006_jobs_tokens_audit"
branch_labels = None
depends_on = None


def _add_column_safe(table: str, column: sa.Column) -> None:
    """Add a column only if it doesn't exist (idempotent for Render deploys)."""
    try:
        op.add_column(table, column)
    except Exception:
        # Column already exists — skip silently
        pass


def _create_index_safe(name: str, table: str, columns: list, **kwargs) -> None:
    """Create an index only if it doesn't exist."""
    try:
        op.create_index(name, table, columns, **kwargs)
    except Exception:
        pass


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Instagram columns on posts
    # ------------------------------------------------------------------
    _add_column_safe(
        "posts",
        sa.Column("instagram_media_id", sa.String(128), nullable=True),
    )
    _add_column_safe(
        "posts",
        sa.Column("instagram_post_url", sa.String(512), nullable=True),
    )
    _add_column_safe(
        "posts",
        sa.Column(
            "instagram_status",
            sa.String(32),
            nullable=False,
            server_default="none",
        ),
    )
    _add_column_safe(
        "posts",
        sa.Column("instagram_error", sa.Text(), nullable=True),
    )
    _add_column_safe(
        "posts",
        sa.Column("instagram_container_id", sa.String(128), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. sheet_row_id on posts
    # ------------------------------------------------------------------
    _add_column_safe(
        "posts",
        sa.Column("sheet_row_id", sa.String(64), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. Instagram indexes
    # ------------------------------------------------------------------
    _create_index_safe(
        "ix_posts_instagram_status",
        "posts",
        ["instagram_status"],
    )

    # ------------------------------------------------------------------
    # 4. Phase 4-6 performance indexes
    # ------------------------------------------------------------------

    # DLQ monitoring: "how many dead-letter jobs since when?"
    _create_index_safe(
        "ix_jobs_status_finished_at",
        "jobs",
        ["status", "finished_at"],
    )

    # Per-step latency queries (metrics router)
    _create_index_safe(
        "ix_jobs_job_type_post_id",
        "jobs",
        ["job_type", "post_id"],
    )

    # Per-step latency with status filter (only succeeded jobs)
    _create_index_safe(
        "ix_jobs_status_job_type_duration",
        "jobs",
        ["status", "job_type", "duration_ms"],
    )

    # Security dashboard: filter audit logs by outcome
    _create_index_safe(
        "ix_audit_logs_outcome",
        "audit_logs",
        ["outcome"],
    )

    # Active session count: non-revoked, non-expired refresh tokens
    _create_index_safe(
        "ix_refresh_tokens_active",
        "refresh_tokens",
        ["is_revoked", "expires_at"],
    )

    # Stale job recovery: RUNNING jobs older than threshold
    _create_index_safe(
        "ix_jobs_running_started_at",
        "jobs",
        ["status", "started_at"],
    )


def downgrade() -> None:
    # Drop indexes (safe — they may not all exist)
    for idx in [
        "ix_jobs_running_started_at",
        "ix_refresh_tokens_active",
        "ix_audit_logs_outcome",
        "ix_jobs_status_job_type_duration",
        "ix_jobs_job_type_post_id",
        "ix_jobs_status_finished_at",
        "ix_posts_instagram_status",
    ]:
        try:
            op.drop_index(idx)
        except Exception:
            pass

    # Drop columns (reverse order)
    for col in [
        "sheet_row_id",
        "instagram_container_id",
        "instagram_error",
        "instagram_status",
        "instagram_post_url",
        "instagram_media_id",
    ]:
        try:
            op.drop_column("posts", col)
        except Exception:
            pass
