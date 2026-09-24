"""
Tests for the Job repository and model.

Covers:
  - Job creation and lifecycle (create → start → succeed/fail)
  - Duration tracking
  - Terminal state detection
  - Dead-letter promotion
  - Count attempts
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

from backend.repositories.job_repository import JobRepository, JobType, JobStatus


def _make_db_with_job(job_attrs: dict | None = None) -> tuple:
    """Helper: create a mock DB session and a mock Job."""
    job = MagicMock()
    job.id = 1
    job.post_id = 182
    job.job_type = JobType.YOUTUBE_UPLOAD
    job.status = JobStatus.CREATED
    job.attempt = 1
    job.started_at = None
    job.finished_at = None
    job.duration_ms = None
    job.worker_id = None
    job.error_message = None
    job.error_traceback = None
    job.output_json = None
    job.external_ref = None
    job.updated_at = None
    if job_attrs:
        for k, v in job_attrs.items():
            setattr(job, k, v)

    db = MagicMock()
    db.get.return_value = job
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = job
    db.query.return_value.filter.return_value.count.return_value = 0
    return db, job


class TestJobLifecycle:
    """Test the full job lifecycle."""

    def test_create_job(self):
        db, _ = _make_db_with_job()
        repo = JobRepository(db)

        created_job = MagicMock()
        created_job.id = 42
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        with patch("backend.repositories.job_repository.Job", return_value=created_job):
            job = repo.create(job_type=JobType.YOUTUBE_UPLOAD, post_id=182)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    def test_start_transitions_to_running(self):
        db, job = _make_db_with_job({"status": JobStatus.CREATED})
        repo = JobRepository(db)

        repo.start(job, worker_id="test-worker-1")

        assert job.status == JobStatus.RUNNING
        assert job.worker_id == "test-worker-1"
        assert job.started_at is not None
        db.commit.assert_called_once()

    def test_succeed_transitions_and_computes_duration(self):
        now = datetime.now(timezone.utc)
        db, job = _make_db_with_job({
            "status": JobStatus.RUNNING,
            "started_at": now - timedelta(seconds=45),
        })
        repo = JobRepository(db)

        repo.succeed(job, output={"video_id": "abc123"}, external_ref="abc123")

        assert job.status == JobStatus.SUCCEEDED
        assert job.finished_at is not None
        assert job.external_ref == "abc123"
        assert job.output_json is not None  # serialized output
        assert job.duration_ms is not None
        assert job.duration_ms >= 44000  # ~45s = 45000ms

    def test_fail_transitions_and_records_error(self):
        db, job = _make_db_with_job({"status": JobStatus.RUNNING, "started_at": datetime.now(timezone.utc)})
        repo = JobRepository(db)

        repo.fail(job, error="YouTube quota exceeded")

        assert job.status == JobStatus.FAILED
        assert "quota exceeded" in job.error_message.lower()
        assert job.finished_at is not None

    def test_fail_with_exception_records_traceback(self):
        db, job = _make_db_with_job({"status": JobStatus.RUNNING, "started_at": datetime.now(timezone.utc)})
        repo = JobRepository(db)

        exc = ValueError("Test error")
        repo.fail(job, error=str(exc), exc=exc)

        assert job.error_traceback is not None
        assert "ValueError" in job.error_traceback

    def test_dead_letter_promotion(self):
        db, job = _make_db_with_job({"status": JobStatus.RUNNING, "started_at": datetime.now(timezone.utc)})
        repo = JobRepository(db)

        repo.fail(job, error="Exhausted after 5 retries", dead_letter=True)

        assert job.status == JobStatus.DEAD_LETTER

    def test_cancel(self):
        db, job = _make_db_with_job({"status": JobStatus.RUNNING})
        repo = JobRepository(db)

        repo.cancel(job, reason="Manual cancellation")

        assert job.status == JobStatus.CANCELLED
        assert job.finished_at is not None


class TestJobTerminalState:
    """Test is_terminal property."""

    @pytest.mark.parametrize("terminal_status", [
        "succeeded", "failed", "cancelled", "dead_letter"
    ])
    def test_terminal_states_are_terminal(self, terminal_status):
        _, job = _make_db_with_job({"status": terminal_status})
        job.is_terminal = (terminal_status in ("succeeded", "failed", "cancelled", "dead_letter"))
        # Use direct check since model property is on real object
        assert terminal_status in JobStatus.TERMINAL

    @pytest.mark.parametrize("active_status", ["created", "scheduled", "running"])
    def test_active_states_are_not_terminal(self, active_status):
        assert active_status not in JobStatus.TERMINAL


class TestJobRepositoryReads:
    """Test read operations."""

    def test_get_returns_job(self):
        db, job = _make_db_with_job()
        db.get.return_value = job
        repo = JobRepository(db)

        result = repo.get(1)
        assert result == job

    def test_get_returns_none_for_missing(self):
        db, _ = _make_db_with_job()
        db.get.return_value = None
        repo = JobRepository(db)

        result = repo.get(9999)
        assert result is None

    def test_count_attempts(self):
        db, _ = _make_db_with_job()
        db.query.return_value.filter.return_value.count.return_value = 3
        repo = JobRepository(db)

        count = repo.count_attempts(post_id=182, job_type=JobType.YOUTUBE_UPLOAD)
        assert count == 3


class TestJobTypeConstants:
    """Ensure job type strings are stable (used as column values in DB)."""

    def test_all_types_are_lowercase_strings(self):
        for attr in ["CLEAN", "ENRICH", "YOUTUBE_UPLOAD", "COMMENT",
                     "INSTAGRAM", "DRIVE_ARCHIVE", "SHEET_SYNC",
                     "ASMR_WORKFLOW", "AUTO_GENERATE"]:
            val = getattr(JobType, attr)
            assert isinstance(val, str)
            assert val == val.lower(), f"JobType.{attr} should be lowercase, got {val!r}"

    def test_job_types_are_unique(self):
        values = [
            JobType.CLEAN, JobType.ENRICH, JobType.YOUTUBE_UPLOAD,
            JobType.COMMENT, JobType.INSTAGRAM, JobType.DRIVE_ARCHIVE,
            JobType.SHEET_SYNC, JobType.ASMR_WORKFLOW, JobType.AUTO_GENERATE,
        ]
        assert len(values) == len(set(values)), "Job types must be unique"
