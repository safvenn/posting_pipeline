"""
Job Repository — data access layer for the jobs table.

All query logic for Job lives here. No raw db.query(Job) calls
should appear outside this module.

Usage:
    from backend.repositories.job_repository import JobRepository

    repo = JobRepository(db)
    job = repo.create(post_id=182, job_type="youtube_upload")
    repo.start(job, worker_id="worker-1")
    repo.succeed(job, output={"video_id": "abc123"})
"""
from __future__ import annotations

import json
import logging
import os
import traceback as tb
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Job

logger = logging.getLogger(__name__)

# Job type constants — single source of truth
class JobType:
    CLEAN           = "clean"
    ENRICH          = "enrich"
    YOUTUBE_UPLOAD  = "youtube_upload"
    COMMENT         = "comment"
    INSTAGRAM       = "instagram_publish"
    DRIVE_ARCHIVE   = "drive_archive"
    SHEET_SYNC      = "sheet_sync"
    ASMR_WORKFLOW   = "asmr_workflow"
    AUTO_GENERATE   = "auto_generate"


# Job status constants
class JobStatus:
    CREATED     = "created"
    SCHEDULED   = "scheduled"
    RUNNING     = "running"
    SUCCEEDED   = "succeeded"
    FAILED      = "failed"
    CANCELLED   = "cancelled"
    DEAD_LETTER = "dead_letter"

    TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, DEAD_LETTER})


_WORKER_ID = f"{os.uname().nodename if hasattr(os, 'uname') else 'host'}-{os.getpid()}"


class JobRepository:
    """Data access for the jobs table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create(
        self,
        job_type: str,
        post_id: Optional[int] = None,
        attempt: int = 1,
        input_data: Optional[dict] = None,
    ) -> Job:
        """Create and persist a new Job in CREATED state."""
        job = Job(
            post_id=post_id,
            job_type=job_type,
            status=JobStatus.CREATED,
            attempt=attempt,
            scheduled_at=datetime.now(timezone.utc),
            input_json=json.dumps(input_data) if input_data else None,
        )
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        logger.debug("job.create type=%s post_id=%s id=%s", job_type, post_id, job.id)
        return job

    def start(self, job: Job, worker_id: Optional[str] = None) -> Job:
        """Transition job to RUNNING and record the start time."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.worker_id = worker_id or _WORKER_ID
        job.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        logger.debug("job.start id=%s worker=%s", job.id, job.worker_id)
        return job

    def succeed(
        self,
        job: Job,
        output: Optional[dict] = None,
        external_ref: Optional[str] = None,
    ) -> Job:
        """Transition job to SUCCEEDED and compute duration."""
        now = datetime.now(timezone.utc)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = now
        job.external_ref = external_ref
        job.output_json = json.dumps(output) if output else None
        job.updated_at = now
        if job.started_at:
            elapsed_ms = int((now - job.started_at).total_seconds() * 1000)
            job.duration_ms = elapsed_ms
        self._db.commit()
        logger.info(
            "job.succeed id=%s type=%s post_id=%s duration_ms=%s",
            job.id, job.job_type, job.post_id, job.duration_ms,
        )
        return job

    def fail(
        self,
        job: Job,
        error: str,
        exc: Optional[BaseException] = None,
        dead_letter: bool = False,
    ) -> Job:
        """Transition job to FAILED (or DEAD_LETTER if exhausted)."""
        now = datetime.now(timezone.utc)
        job.status = JobStatus.DEAD_LETTER if dead_letter else JobStatus.FAILED
        job.finished_at = now
        job.error_message = error[:2000]
        job.updated_at = now
        if exc is not None:
            job.error_traceback = "".join(tb.format_exception(type(exc), exc, exc.__traceback__))[:5000]
        if job.started_at:
            job.duration_ms = int((now - job.started_at).total_seconds() * 1000)
        self._db.commit()
        logger.warning(
            "job.fail id=%s type=%s post_id=%s status=%s error=%s",
            job.id, job.job_type, job.post_id, job.status, error[:200],
        )
        return job

    def cancel(self, job: Job, reason: str = "") -> Job:
        """Transition job to CANCELLED."""
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = reason[:2000] if reason else None
        job.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        return job

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, job_id: int) -> Optional[Job]:
        return self._db.get(Job, job_id)

    def get_latest_for_post(
        self,
        post_id: int,
        job_type: Optional[str] = None,
    ) -> Optional[Job]:
        """Return the most recent job for a post, optionally filtered by type."""
        q = self._db.query(Job).filter(Job.post_id == post_id)
        if job_type:
            q = q.filter(Job.job_type == job_type)
        return q.order_by(Job.created_at.desc()).first()

    def list_for_post(self, post_id: int, limit: int = 20) -> list[Job]:
        """Return all jobs for a post, newest first."""
        return (
            self._db.query(Job)
            .filter(Job.post_id == post_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )

    def count_attempts(self, post_id: int, job_type: str) -> int:
        """Return the number of attempts for a specific job_type on a post."""
        return (
            self._db.query(Job)
            .filter(Job.post_id == post_id, Job.job_type == job_type)
            .count()
        )

    def list_running(self) -> list[Job]:
        """Return all currently running jobs (for stale lock detection)."""
        return (
            self._db.query(Job)
            .filter(Job.status == JobStatus.RUNNING)
            .order_by(Job.started_at.asc())
            .all()
        )

    def list_dead_letters(self, limit: int = 50) -> list[Job]:
        """Return jobs in dead-letter state, oldest first."""
        return (
            self._db.query(Job)
            .filter(Job.status == JobStatus.DEAD_LETTER)
            .order_by(Job.created_at.asc())
            .limit(limit)
            .all()
        )

    def cleanup_old(self, keep_days: int = 30) -> int:
        """
        Delete succeeded/cancelled jobs older than keep_days.
        Keeps failed and dead_letter jobs indefinitely for audit.
        Returns count deleted.
        """
        from datetime import timedelta
        from sqlalchemy import delete
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        result = (
            self._db.execute(
                __import__("sqlalchemy").delete(Job).where(
                    Job.status.in_([JobStatus.SUCCEEDED, JobStatus.CANCELLED]),
                    Job.created_at < cutoff,
                )
            )
        )
        self._db.commit()
        count = result.rowcount
        if count:
            logger.info("job.cleanup deleted %d old jobs (keep_days=%d)", count, keep_days)
        return count

    def requeue(self, job: Job, actor: str = "operator") -> Job:
        """
        Re-queue a FAILED or DEAD_LETTER job for another attempt.

        Resets the job back to CREATED state with:
          - incremented attempt count
          - cleared started_at / finished_at / duration_ms
          - cleared error_message / error_traceback
          - preserved input_json (same inputs replayed)
          - new scheduled_at = now

        This is the manual retry path. Automatic retry via schedule_retry()
        happens inside each job's business logic.
        """
        if job.status not in (JobStatus.FAILED, JobStatus.DEAD_LETTER):
            raise ValueError(
                f"Job {job.id} is in '{job.status}' state — "
                f"only FAILED or DEAD_LETTER jobs can be re-queued"
            )
        now = datetime.now(timezone.utc)
        old_status = job.status
        job.status = JobStatus.CREATED
        job.attempt = (job.attempt or 1) + 1
        job.scheduled_at = now
        job.started_at = None
        job.finished_at = None
        job.duration_ms = None
        job.worker_id = None
        job.error_message = f"[Re-queued by {actor} from {old_status} at {now.isoformat()}]"
        job.error_traceback = None
        job.updated_at = now
        self._db.commit()
        logger.info(
            "job.requeue id=%s type=%s post_id=%s attempt=%s actor=%s",
            job.id, job.job_type, job.post_id, job.attempt, actor,
        )
        return job

    def count_dead_letters(self) -> int:
        """Return total jobs in dead_letter state."""
        return (
            self._db.query(Job)
            .filter(Job.status == JobStatus.DEAD_LETTER)
            .count()
        )

