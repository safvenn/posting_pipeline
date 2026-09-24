"""Add jobs, refresh_tokens, and audit_logs tables.

Revision ID: 0006_jobs_tokens_audit
Revises: 0005_idempotency
Create Date: 2026-09-24

Purpose:
    Phase 2 data model additions:

    1. jobs — Durable execution record per pipeline step.
       Separates EXECUTION state from BUSINESS state (post.status).
       Enables retry auditing, per-step latency, worker tracking, DLQ visibility.

    2. refresh_tokens — Server-side revocable refresh token store.
       Eliminates the security gap where stolen refresh tokens could not
       be invalidated without rotating the JWT secret.
       Stores SHA-256 hash of token only (never raw token).

    3. audit_logs — Append-only security and admin action trail.
       Records: login/logout events, post mutations, config changes.
       No foreign keys — preserves integrity even when referenced rows deleted.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_jobs_tokens_audit"
down_revision = "0005_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("worker_id", sa.String(256), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.String(256), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"],
            name="fk_jobs_post_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_jobs_id", "jobs", ["id"])
    op.create_index("ix_jobs_post_id", "jobs", ["post_id"])
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_post_id_created_at", "jobs", ["post_id", "created_at"])
    op.create_index("ix_jobs_status_scheduled_at", "jobs", ["status", "scheduled_at"])
    op.create_index("ix_jobs_status_started_at", "jobs", ["status", "started_at"])

    # ------------------------------------------------------------------
    # refresh_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("device_id", sa.String(256), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("issued_to_ip", sa.String(64), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(64), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
    )
    op.create_index("ix_refresh_tokens_id", "refresh_tokens", ["id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_username", "refresh_tokens", ["username"])
    op.create_index("ix_refresh_tokens_is_revoked", "refresh_tokens", ["is_revoked"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("actor_ip", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False, server_default="success"),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_created_at", "audit_logs", ["actor", "created_at"])
    op.create_index(
        "ix_audit_logs_event_type_created_at", "audit_logs", ["event_type", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_resource_created_at",
        "audit_logs",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    # Drop in reverse order
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("jobs")
