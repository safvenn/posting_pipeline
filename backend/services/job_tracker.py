"""
JobTracker — context manager for automatic Job lifecycle tracking.

Wraps any pipeline step with a durable Job record that captures:
  - Step type and post
  - Which worker picked it up
  - Start time, finish time, duration
  - Success output or failure error + traceback
  - External reference (video_id, media_id, etc.)

Usage (wrap any existing job entry point):

    from backend.services.job_tracker import JobTracker
    from backend.repositories.job_repository import JobType

    def upload_one_post(post_id: int) -> None:
        with JobTracker(post_id, JobType.YOUTUBE_UPLOAD) as tracker:
            # existing upload logic here
            video_id = _upload_single_post(post, db)
            tracker.set_output({"video_id": video_id}, external_ref=video_id)

Design:
  - DB session is opened/closed inside the tracker (independent of the
    calling function's session — avoids cross-session contamination)
  - Failure is captured automatically via __exit__
  - Never raises: any JobTracker internal error is logged and swallowed
    so it NEVER disrupts existing business logic
  - Idempotent start: if a job record cannot be created, tracking is
    silently disabled (NOOP mode) for that execution

The tracker is intentionally a thin wrapper. It does NOT implement
any business logic — that remains in the job functions untouched.
"""
from __future__ import annotations

import logging
import sys
import traceback as tb
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional

from backend.database import SessionLocal
from backend.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


class _NoopTracker:
    """Returned when JobTracker fails to create a DB record — silently skips all tracking."""
    def set_output(self, output: dict, external_ref: Optional[str] = None) -> None:
        pass
    def set_external_ref(self, ref: str) -> None:
        pass


class _ActiveTracker:
    """Wraps a live Job record and exposes output/ref setters."""

    def __init__(self, job, repo) -> None:
        self._job = job
        self._repo = repo
        self._output: Optional[dict] = None
        self._external_ref: Optional[str] = None

    def set_output(self, output: dict, external_ref: Optional[str] = None) -> None:
        """Call this after a successful external API call to record what was returned."""
        self._output = output
        if external_ref:
            self._external_ref = external_ref

    def set_external_ref(self, ref: str) -> None:
        """Set the external reference (e.g., YouTube video_id) for this job."""
        self._external_ref = ref

    def _finish_success(self) -> None:
        self._repo.succeed(
            self._job,
            output=self._output,
            external_ref=self._external_ref,
        )

    def _finish_failure(self, exc: Optional[BaseException], error: str) -> None:
        self._repo.fail(self._job, error=error, exc=exc)


@contextmanager
def JobTracker(
    post_id: Optional[int],
    job_type: str,
    input_data: Optional[dict] = None,
) -> Generator[_ActiveTracker | _NoopTracker, None, None]:
    """
    Context manager that creates and manages a Job record for a pipeline step.

    Args:
        post_id:    The Post.id this job is for. None for system-level jobs.
        job_type:   One of the JobType constants (e.g., JobType.YOUTUBE_UPLOAD).
        input_data: Optional dict of input parameters to record on the Job row.

    Yields:
        tracker: An _ActiveTracker or _NoopTracker (if DB unavailable).

    Example:
        with JobTracker(post_id=182, job_type=JobType.YOUTUBE_UPLOAD) as tracker:
            video_id = _do_upload(...)
            tracker.set_output({"video_id": video_id}, external_ref=video_id)
        # Job is now SUCCEEDED with output recorded
        # Any exception inside the with-block → Job is FAILED with traceback
    """
    db = None
    tracker: _ActiveTracker | _NoopTracker = _NoopTracker()

    try:
        db = SessionLocal()
        repo = JobRepository(db)
        attempt = repo.count_attempts(post_id, job_type) + 1 if post_id else 1
        job = repo.create(job_type=job_type, post_id=post_id, attempt=attempt, input_data=input_data)
        repo.start(job)
        tracker = _ActiveTracker(job, repo)
    except Exception as exc:
        logger.debug("JobTracker: failed to create job record for %s post_id=%s: %s", job_type, post_id, exc)
        tracker = _NoopTracker()
        if db:
            try:
                db.close()
            except Exception:
                pass
        db = None

    exc_info = None
    try:
        yield tracker
    except Exception:
        exc_info = sys.exc_info()
        raise
    finally:
        if isinstance(tracker, _ActiveTracker):
            try:
                if exc_info is not None:
                    exc_type, exc_val, exc_tb = exc_info
                    error_str = f"{exc_type.__name__}: {exc_val}" if exc_val else "Unknown error"
                    tracker._finish_failure(exc=exc_val, error=error_str)
                else:
                    tracker._finish_success()
            except Exception as finish_exc:
                logger.debug("JobTracker: failed to finish job record: %s", finish_exc)
        if db:
            try:
                db.close()
            except Exception:
                pass
