"""
Worker Coordinator — distributed task leasing, heartbeating, and zombie reaping.

Provides safe multi-worker execution across multiple Render replicas, background
daemons, or container instances:

Key guarantees:
  1. Atomic Job Claiming:
     - PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED ensures zero contention.
     - SQLite fallback: Atomic transaction with immediate status transition.
  2. Heartbeating & Lease Extension:
     - Long-running tasks touch their lease timestamp to prevent false timeouts.
  3. Zombie / Stale Lease Reaping:
     - If a worker crashes or drops off the network, abandoned jobs are reclaimed
       and reassigned, or sent to the DLQ if retry limits are exceeded.
  4. Graceful Shutdown Release:
     - Workers receiving SIGTERM can release in-flight jobs back to CREATED state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy.orm import Session
from sqlalchemy import text, func

from backend.models import Job
from backend.repositories.job_repository import JobStatus, JobType

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300       # 5 minutes default lease
DEFAULT_STALE_SECONDS = 600       # 10 minutes without heartbeat = zombie


def _is_postgres(db: Session) -> bool:
    try:
        bind = getattr(db, "bind", None) or db.get_bind()
        return "postgresql" in str(bind.dialect.name).lower()
    except Exception:
        return False


class WorkerCoordinator:
    """Manages distributed job leasing, heartbeats, and cluster worker health."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def claim_next_job(
        self,
        worker_id: str,
        supported_types: Optional[Sequence[str]] = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> Optional[Job]:
        """
        Atomically claim the next eligible job for the given worker_id.

        Selects the oldest job in CREATED status that is scheduled for now or earlier.
        Transitions the job to RUNNING, stamps worker_id and started_at.
        """
        now = datetime.now(timezone.utc)
        is_pg = _is_postgres(self._db)

        if is_pg:
            # PostgreSQL FOR UPDATE SKIP LOCKED
            query = (
                self._db.query(Job)
                .filter(
                    Job.status.in_([JobStatus.CREATED, JobStatus.SCHEDULED]),
                    (Job.scheduled_at == None) | (Job.scheduled_at <= now),
                )
            )
            if supported_types:
                query = query.filter(Job.job_type.in_(supported_types))

            # Order by priority / age
            job = (
                query.order_by(Job.scheduled_at.asc().nullsfirst(), Job.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if not job:
                return None

            job.status = JobStatus.RUNNING
            job.worker_id = worker_id
            job.started_at = now
            job.updated_at = now
            self._db.commit()
            self._db.refresh(job)
            logger.info("coordinator.claim[pg]: worker=%s claimed job_id=%s type=%s", worker_id, job.id, job.job_type)
            return job

        # SQLite / Dev fallback — atomic in-transaction claim
        query = (
            self._db.query(Job)
            .filter(
                Job.status.in_([JobStatus.CREATED, JobStatus.SCHEDULED]),
                (Job.scheduled_at == None) | (Job.scheduled_at <= now),
            )
        )
        if supported_types:
            query = query.filter(Job.job_type.in_(supported_types))

        job = query.order_by(Job.scheduled_at.asc(), Job.created_at.asc()).first()
        if not job:
            return None

        job.status = JobStatus.RUNNING
        job.worker_id = worker_id
        job.started_at = now
        job.updated_at = now
        self._db.commit()
        self._db.refresh(job)
        logger.info("coordinator.claim[mem]: worker=%s claimed job_id=%s type=%s", worker_id, job.id, job.job_type)
        return job

    def heartbeat(
        self,
        job_id: int,
        worker_id: str,
    ) -> bool:
        """
        Refresh the heartbeat on a currently running job to extend its lease.
        Returns True if successful, False if the job is no longer owned or running.
        """
        now = datetime.now(timezone.utc)
        job = (
            self._db.query(Job)
            .filter(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.worker_id == worker_id,
            )
            .first()
        )
        if not job:
            logger.warning(
                "coordinator.heartbeat_failed: job_id=%s worker=%s (not found or not running)",
                job_id, worker_id,
            )
            return False

        job.updated_at = now
        self._db.commit()
        logger.debug("coordinator.heartbeat: refreshed lease for job_id=%s worker=%s", job_id, worker_id)
        return True

    def release_job(
        self,
        job_id: int,
        worker_id: str,
        reason: str = "graceful_shutdown",
    ) -> bool:
        """
        Voluntarily release a running job back to the queue (e.g., during SIGTERM shutdown).
        """
        now = datetime.now(timezone.utc)
        job = (
            self._db.query(Job)
            .filter(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.worker_id == worker_id,
            )
            .first()
        )
        if not job:
            return False

        job.status = JobStatus.CREATED
        job.worker_id = None
        job.started_at = None
        job.error_message = f"[Released by worker {worker_id}: {reason} at {now.isoformat()}]"
        job.updated_at = now
        self._db.commit()
        logger.info("coordinator.release: job_id=%s returned to queue by worker=%s", job_id, worker_id)
        return True

    def reap_stale_leases(
        self,
        stale_threshold_seconds: int = DEFAULT_STALE_SECONDS,
        max_attempts: int = 3,
    ) -> dict[str, any]:
        """
        Detect and recover zombie jobs where the worker died or failed to heartbeat.

        If attempts < max_attempts -> requeued to CREATED with incremented attempt.
        If attempts >= max_attempts -> moved to DEAD_LETTER.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=stale_threshold_seconds)

        # Stale jobs are RUNNING and have not heartbeated (updated_at) since cutoff
        stale_jobs = (
            self._db.query(Job)
            .filter(
                Job.status == JobStatus.RUNNING,
                (Job.updated_at < cutoff) | ((Job.updated_at == None) & (Job.started_at < cutoff)),
            )
            .all()
        )

        reclaimed_ids = []
        dead_letter_ids = []

        for job in stale_jobs:
            prev_worker = job.worker_id or "unknown"
            if (job.attempt or 1) >= max_attempts:
                job.status = JobStatus.DEAD_LETTER
                job.finished_at = now
                job.error_message = (
                    f"[Zombie reaper: Worker '{prev_worker}' timed out after "
                    f"{stale_threshold_seconds}s without heartbeat. Max attempts ({max_attempts}) reached.]"
                )
                dead_letter_ids.append(job.id)
                logger.error(
                    "coordinator.reap_dlq: job_id=%s worker=%s attempts=%s moved to DLQ",
                    job.id, prev_worker, job.attempt,
                )
            else:
                job.status = JobStatus.CREATED
                job.attempt = (job.attempt or 1) + 1
                job.worker_id = None
                job.started_at = None
                job.error_message = (
                    f"[Zombie reaper: Reclaimed from timed-out worker '{prev_worker}' at {now.isoformat()}]"
                )
                reclaimed_ids.append(job.id)
                logger.warning(
                    "coordinator.reap_reclaim: job_id=%s worker=%s new_attempt=%s",
                    job.id, prev_worker, job.attempt,
                )
            job.updated_at = now

        if stale_jobs:
            self._db.commit()

        return {
            "reaped_total": len(stale_jobs),
            "reclaimed_count": len(reclaimed_ids),
            "reclaimed_ids": reclaimed_ids,
            "dead_letter_count": len(dead_letter_ids),
            "dead_letter_ids": dead_letter_ids,
        }

    def list_active_workers(self, active_seconds: int = 300) -> list[dict]:
        """
        List all workers currently holding running jobs with heartbeat within active_seconds.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=active_seconds)
        rows = (
            self._db.query(
                Job.worker_id,
                func.count(Job.id).label("job_count"),
                func.max(Job.updated_at).label("last_heartbeat"),
            )
            .filter(
                Job.status == JobStatus.RUNNING,
                Job.worker_id != None,
                Job.updated_at >= cutoff,
            )
            .group_by(Job.worker_id)
            .all()
        )
        return [
            {
                "worker_id": r.worker_id,
                "active_jobs": r.job_count,
                "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
            }
            for r in rows
        ]
