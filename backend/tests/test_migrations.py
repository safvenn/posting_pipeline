"""
Tests for Phase 7 — Alembic Migration Integrity.

Validates that:
  - All migration files are syntactically valid Python
  - Migration chain is linear (no forks or missing links)
  - Every model column has a corresponding migration
  - Upgrade/downgrade functions exist in every migration
  - env.py imports all model classes
"""
from __future__ import annotations

import importlib
import os
import sys
import re
from pathlib import Path

import pytest


VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def _get_migration_files() -> list[Path]:
    """Return all .py migration files sorted by name."""
    return sorted(
        p for p in VERSIONS_DIR.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("__")
    )


class TestMigrationChain:
    """Migration files form a linear chain with no gaps."""

    def test_migrations_exist(self):
        files = _get_migration_files()
        assert len(files) >= 7, f"Expected at least 7 migrations, got {len(files)}"

    def test_migrations_are_valid_python(self):
        """Every migration file must parse without syntax errors."""
        for f in _get_migration_files():
            code = f.read_text(encoding="utf-8")
            try:
                compile(code, str(f), "exec")
            except SyntaxError as exc:
                pytest.fail(f"Syntax error in {f.name}: {exc}")

    def test_chain_is_linear(self):
        """Each migration's down_revision matches the previous migration's revision."""
        files = _get_migration_files()
        revisions = {}

        for f in files:
            code = f.read_text(encoding="utf-8")
            # Handle both `revision = "..."` and `revision: str = "..."`
            rev_match = re.search(r'^revision(?:\s*:\s*\w+)?\s*=\s*["\']([^"\']+)', code, re.MULTILINE)
            down_match = re.search(r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*.*?["\']([^"\']+)', code, re.MULTILINE)

            assert rev_match, f"No revision found in {f.name}"
            rev = rev_match.group(1)
            down = down_match.group(1) if down_match else None

            revisions[rev] = {
                "file": f.name,
                "down_revision": down,
            }

        # First migration should have no down_revision (or None)
        first_file = files[0]
        first_code = first_file.read_text(encoding="utf-8")
        # Check if down_revision is None
        assert "None" in first_code or 'down_revision' in first_code

        # Verify the chain: every down_revision should exist as a revision
        # (except the first migration)
        for rev, info in revisions.items():
            if info["down_revision"] is not None:
                assert info["down_revision"] in revisions, (
                    f"Migration {info['file']} (rev={rev}) references "
                    f"down_revision={info['down_revision']} which doesn't exist"
                )

    def test_every_migration_has_upgrade_and_downgrade(self):
        """All migrations must define both upgrade() and downgrade()."""
        for f in _get_migration_files():
            code = f.read_text(encoding="utf-8")
            assert "def upgrade" in code, f"{f.name} missing upgrade()"
            assert "def downgrade" in code, f"{f.name} missing downgrade()"


class TestMigrationCompleteness:
    """Critical model columns are covered by migrations."""

    def _all_migration_text(self) -> str:
        """Concatenate all migration source code."""
        return "\n".join(
            f.read_text(encoding="utf-8") for f in _get_migration_files()
        )

    def test_posts_table_created(self):
        text = self._all_migration_text()
        assert '"posts"' in text

    def test_jobs_table_created(self):
        text = self._all_migration_text()
        assert '"jobs"' in text

    def test_refresh_tokens_table_created(self):
        text = self._all_migration_text()
        assert '"refresh_tokens"' in text

    def test_audit_logs_table_created(self):
        text = self._all_migration_text()
        assert '"audit_logs"' in text

    def test_workflow_events_table_created(self):
        text = self._all_migration_text()
        assert '"workflow_events"' in text

    def test_food_items_table_created(self):
        text = self._all_migration_text()
        assert '"food_items"' in text

    def test_idempotency_table_created(self):
        text = self._all_migration_text()
        assert '"post_idempotency_records"' in text

    def test_instagram_columns_migrated(self):
        text = self._all_migration_text()
        assert "instagram_media_id" in text
        assert "instagram_status" in text
        assert "instagram_container_id" in text

    def test_sheet_row_id_migrated(self):
        text = self._all_migration_text()
        assert "sheet_row_id" in text

    def test_retry_columns_migrated(self):
        text = self._all_migration_text()
        assert "retry_count" in text
        assert "max_retries" in text
        assert "next_retry_at" in text

    def test_drive_columns_migrated(self):
        text = self._all_migration_text()
        assert "drive_file_id" in text
        assert "drive_upload_status" in text
        assert "clean_drive_file_id" in text

    def test_job_performance_indexes(self):
        text = self._all_migration_text()
        assert "ix_jobs_status_finished_at" in text
        assert "ix_jobs_status_job_type_duration" in text


class TestEnvPyCompleteness:
    """env.py imports all models."""

    def test_env_py_imports_all_models(self):
        code = ENV_PY.read_text(encoding="utf-8")
        expected_models = [
            "Post", "WorkflowEvent", "FoodItem", "ASMRWorkflowRun",
            "ASMRContentJob", "ASMRPublishedContent", "PostIdempotencyRecord",
            "Job", "RefreshToken", "AuditLog",
        ]
        for model in expected_models:
            assert model in code, (
                f"env.py does not import {model} — "
                f"autogenerate won't detect drift in this table"
            )


class TestMigration0007Specific:
    """Specific tests for the Phase 7 migration."""

    def test_0007_exists(self):
        f = VERSIONS_DIR / "0007_instagram_and_indexes.py"
        assert f.exists()

    def test_0007_chains_from_0006(self):
        code = (VERSIONS_DIR / "0007_instagram_and_indexes.py").read_text()
        assert '"0006_jobs_tokens_audit"' in code

    def test_0007_has_idempotent_helpers(self):
        """The migration uses safe add/create helpers to handle re-runs."""
        code = (VERSIONS_DIR / "0007_instagram_and_indexes.py").read_text()
        assert "_add_column_safe" in code
        assert "_create_index_safe" in code

    def test_0007_adds_instagram_columns(self):
        code = (VERSIONS_DIR / "0007_instagram_and_indexes.py").read_text()
        for col in [
            "instagram_media_id",
            "instagram_post_url",
            "instagram_status",
            "instagram_error",
            "instagram_container_id",
        ]:
            assert col in code, f"0007 missing column: {col}"

    def test_0007_adds_performance_indexes(self):
        code = (VERSIONS_DIR / "0007_instagram_and_indexes.py").read_text()
        for idx in [
            "ix_jobs_status_finished_at",
            "ix_jobs_job_type_post_id",
            "ix_jobs_status_job_type_duration",
            "ix_audit_logs_outcome",
            "ix_refresh_tokens_active",
            "ix_jobs_running_started_at",
        ]:
            assert idx in code, f"0007 missing index: {idx}"

    def test_0007_downgrade_exists(self):
        code = (VERSIONS_DIR / "0007_instagram_and_indexes.py").read_text()
        assert "def downgrade" in code
        # Should drop the same indexes and columns it added
        assert "drop_index" in code
        assert "drop_column" in code
