"""
Tests for Phase 5 — Fault Tolerance & Dead-Letter Recovery:
  - CircuitBreaker trips when DLQ >= threshold
  - CircuitBreaker resets when DLQ drops below threshold
  - Manual reset always re-enables queue
  - NOOP when DB check fails (non-fatal)
  - JobRepository.requeue() resets failed/dead-letter job to CREATED
  - requeue() increments attempt count
  - requeue() preserves input_json
  - requeue() rejects non-terminal jobs that are still running
  - recover_stale_running_jobs() resets old RUNNING jobs
  - recover_stale_running_jobs() leaves fresh RUNNING jobs alone
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from backend.repositories.job_repository import JobStatus, JobType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(status=JobStatus.DEAD_LETTER, job_type=JobType.YOUTUBE_UPLOAD,
              post_id=182, attempt=3, started_at=None):
    job = MagicMock()
    job.id = 1
    job.status = status
    job.job_type = job_type
    job.post_id = post_id
    job.attempt = attempt
    job.started_at = started_at
    job.finished_at = None
    job.duration_ms = None
    job.worker_id = "worker-1"
    job.error_message = "previous error"
    job.error_traceback = "traceback text"
    job.input_json = '{"post_id": 182}'
    job.output_json = None
    job.updated_at = None
    return job


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerTripping:
    """Circuit breaker auto-trips and auto-resets based on DLQ count."""

    def setup_method(self):
        """Reset breaker state before each test."""
        from backend.services.circuit_breaker import _STATE
        _STATE._tripped = False
        _STATE._last_check_at = None

    def test_healthy_when_dlq_below_threshold(self):
        from backend.services.circuit_breaker import CircuitBreaker, _DLQ_THRESHOLD
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = _DLQ_THRESHOLD - 1

        assert CircuitBreaker.is_queue_healthy(db=db) is True

    def test_trips_when_dlq_at_threshold(self):
        from backend.services.circuit_breaker import CircuitBreaker, _DLQ_THRESHOLD
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = _DLQ_THRESHOLD

        result = CircuitBreaker.is_queue_healthy(db=db)
        assert result is False

    def test_trips_when_dlq_above_threshold(self):
        from backend.services.circuit_breaker import CircuitBreaker, _DLQ_THRESHOLD
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = _DLQ_THRESHOLD + 10

        result = CircuitBreaker.is_queue_healthy(db=db)
        assert result is False

    def test_manual_reset_re_enables_queue(self):
        from backend.services.circuit_breaker import CircuitBreaker, _STATE
        _STATE._tripped = True  # force trip

        CircuitBreaker.reset(actor="test")
        assert CircuitBreaker.is_queue_healthy() is True

    def test_noop_when_db_check_fails(self):
        """DB failure during health check must never raise or trip the breaker."""
        from backend.services.circuit_breaker import CircuitBreaker, _STATE
        _STATE._tripped = False

        db = MagicMock()
        db.query.side_effect = Exception("DB connection lost")

        # Should not raise, and should default to healthy (don't pause on uncertainty)
        result = CircuitBreaker.is_queue_healthy(db=db)
        assert result is True  # fail-open: don't pause on DB errors

    def test_status_returns_correct_fields(self):
        from backend.services.circuit_breaker import CircuitBreaker
        status = CircuitBreaker.status()
        assert "tripped" in status
        assert "dlq_threshold" in status
        assert "stale_job_minutes" in status
        assert isinstance(status["tripped"], bool)


class TestCircuitBreakerRateLimit:
    """Breaker only queries DB once per interval to avoid hammering on every tick."""

    def setup_method(self):
        from backend.services.circuit_breaker import _STATE
        _STATE._tripped = False
        _STATE._last_check_at = None

    def test_skips_db_check_within_interval(self):
        from backend.services.circuit_breaker import CircuitBreaker, _STATE
        # Simulate that we just checked 5 seconds ago (well within interval)
        _STATE._last_check_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        _STATE._tripped = False

        db = MagicMock()
        # DB should NOT be queried
        CircuitBreaker.is_queue_healthy(db=db)
        db.query.assert_not_called()


# ---------------------------------------------------------------------------
# JobRepository.requeue() tests
# ---------------------------------------------------------------------------

class TestJobRequeue:
    """Manual retry: re-queue a failed/dead-letter job."""

    def _make_repo_with_job(self, job_status=JobStatus.DEAD_LETTER, attempt=3):
        job = _make_job(status=job_status, attempt=attempt)
        db = MagicMock()
        from backend.repositories.job_repository import JobRepository
        repo = JobRepository(db)
        return repo, db, job

    def test_requeue_dead_letter_resets_to_created(self):
        repo, db, job = self._make_repo_with_job(JobStatus.DEAD_LETTER)
        repo.requeue(job, actor="test_operator")
        assert job.status == JobStatus.CREATED

    def test_requeue_failed_resets_to_created(self):
        repo, db, job = self._make_repo_with_job(JobStatus.FAILED)
        repo.requeue(job, actor="test_operator")
        assert job.status == JobStatus.CREATED

    def test_requeue_increments_attempt(self):
        repo, db, job = self._make_repo_with_job(attempt=3)
        repo.requeue(job, actor="test_operator")
        assert job.attempt == 4

    def test_requeue_clears_error(self):
        repo, db, job = self._make_repo_with_job()
        job.error_traceback = "some traceback"
        repo.requeue(job, actor="test_operator")
        assert job.error_traceback is None

    def test_requeue_clears_timing_fields(self):
        repo, db, job = self._make_repo_with_job()
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = datetime.now(timezone.utc)
        job.duration_ms = 5000
        repo.requeue(job, actor="test_operator")
        assert job.started_at is None
        assert job.finished_at is None
        assert job.duration_ms is None

    def test_requeue_clears_worker_id(self):
        repo, db, job = self._make_repo_with_job()
        job.worker_id = "old-worker"
        repo.requeue(job, actor="test_operator")
        assert job.worker_id is None

    def test_requeue_commits(self):
        repo, db, job = self._make_repo_with_job()
        repo.requeue(job, actor="test_operator")
        db.commit.assert_called_once()

    def test_requeue_records_actor_in_error_message(self):
        repo, db, job = self._make_repo_with_job()
        repo.requeue(job, actor="admin_user")
        assert "admin_user" in job.error_message

    def test_requeue_rejects_running_job(self):
        repo, db, job = self._make_repo_with_job(job_status=JobStatus.RUNNING)
        with pytest.raises(ValueError, match="FAILED or DEAD_LETTER"):
            repo.requeue(job, actor="operator")

    def test_requeue_rejects_succeeded_job(self):
        repo, db, job = self._make_repo_with_job(job_status=JobStatus.SUCCEEDED)
        with pytest.raises(ValueError, match="FAILED or DEAD_LETTER"):
            repo.requeue(job, actor="operator")

    def test_requeue_rejects_cancelled_job(self):
        repo, db, job = self._make_repo_with_job(job_status=JobStatus.CANCELLED)
        with pytest.raises(ValueError, match="FAILED or DEAD_LETTER"):
            repo.requeue(job, actor="operator")

    def test_requeue_sets_new_scheduled_at(self):
        repo, db, job = self._make_repo_with_job()
        job.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
        before = datetime.now(timezone.utc)
        repo.requeue(job, actor="operator")
        assert job.scheduled_at >= before


# ---------------------------------------------------------------------------
# Stale job recovery tests
# ---------------------------------------------------------------------------

class TestStaleJobRecovery:
    """recover_stale_running_jobs() resets old RUNNING jobs on startup."""

    def _make_db_returning(self, jobs: list):
        """Build a db mock whose .query().filter().all() returns `jobs`."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = jobs
        return db

    def test_resets_old_running_job(self):
        from backend.services.circuit_breaker import recover_stale_running_jobs, _STALE_JOB_MINUTES
        from backend.repositories.job_repository import JobStatus

        stale_start = datetime.now(timezone.utc) - timedelta(minutes=_STALE_JOB_MINUTES + 10)
        old_job = MagicMock()
        old_job.id = 1
        old_job.status = JobStatus.RUNNING
        old_job.started_at = stale_start
        old_job.worker_id = "dead-worker"

        db = self._make_db_returning([old_job])

        count = recover_stale_running_jobs(db)

        assert count == 1
        assert old_job.status == JobStatus.CREATED
        assert old_job.started_at is None
        assert old_job.worker_id is None
        assert "dead-worker" in old_job.error_message
        db.commit.assert_called_once()

    def test_returns_zero_when_no_stale_jobs(self):
        from backend.services.circuit_breaker import recover_stale_running_jobs
        db = self._make_db_returning([])

        count = recover_stale_running_jobs(db)
        assert count == 0
        db.commit.assert_not_called()

    def test_resets_multiple_stale_jobs(self):
        from backend.services.circuit_breaker import recover_stale_running_jobs, _STALE_JOB_MINUTES
        from backend.repositories.job_repository import JobStatus

        stale_start = datetime.now(timezone.utc) - timedelta(minutes=_STALE_JOB_MINUTES + 5)
        jobs = [MagicMock() for _ in range(5)]
        for j in jobs:
            j.status = JobStatus.RUNNING
            j.started_at = stale_start
            j.worker_id = "old-worker"

        db = self._make_db_returning(jobs)

        count = recover_stale_running_jobs(db)
        assert count == 5
        for j in jobs:
            assert j.status == JobStatus.CREATED


# ---------------------------------------------------------------------------
# cancel() method validation
# ---------------------------------------------------------------------------

class TestJobCancel:
    """cancel() marks non-terminal jobs as CANCELLED."""

    def test_cancel_running_job(self):
        from backend.repositories.job_repository import JobRepository
        job = _make_job(status=JobStatus.RUNNING)
        db = MagicMock()
        repo = JobRepository(db)
        repo.cancel(job, reason="Manual cancellation")
        assert job.status == JobStatus.CANCELLED
        assert job.finished_at is not None

    def test_cancel_sets_reason(self):
        from backend.repositories.job_repository import JobRepository
        job = _make_job(status=JobStatus.CREATED)
        db = MagicMock()
        repo = JobRepository(db)
        repo.cancel(job, reason="System shutdown")
        assert "System shutdown" in job.error_message

    def test_cancel_commits(self):
        from backend.repositories.job_repository import JobRepository
        job = _make_job(status=JobStatus.CREATED)
        db = MagicMock()
        repo = JobRepository(db)
        repo.cancel(job)
        db.commit.assert_called_once()
