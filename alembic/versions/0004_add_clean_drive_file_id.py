"""Add clean_drive_file_id to posts.

Revision ID: 0004_add_clean_drive_file_id
Revises: 0003_workflow_events
Create Date: 2026-09-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_add_clean_drive_file_id"
down_revision = "0003_workflow_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("clean_drive_file_id", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "clean_drive_file_id")
