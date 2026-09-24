"""
Circuit Breaker — auto-pauses the serial queue when DLQ count exceeds a threshold.

Design:
  - DLQ threshold: if ≥ N jobs are in dead_letter state, the queue is considered
    "broken" and the serial queue runner returns early without processing new work.
  - The threshold is configurable via env var CIRCUIT_BREAKER_DLQ_THRESHOLD (default: 5).
  - State is tracked in-process (not persisted). A deploy/restart resets the breaker.
  - When tripped, a WARNING is logged every 30s (one per queue tick). Alerts/paging
    should be based on this log line or the /api/metrics endpoint.
  - Manual reset: operator calls POST /api/jobs/circuit-breaker/reset to re-enable
    the queue without restarting the process.

Stale lock detection:
  - Jobs stuck in RUNNING for longer than STALE_JOB_THRESHOLD_MINUTES are
    considered orphaned (worker died without finishing).
  - On each queue tick, stale running jobs are reset to CREATED so they can be
    picked up again on the next tick.
  - Only applies when the originating worker_id matches the current process
    (avoids incorrectly resetting jobs from other pods in multi-instance setups).

Usage (in job_queue.py run_serial_queue):
    from backend.services.circuit_breaker import CircuitBreaker

    if not CircuitBreaker.is_queue_healthy():
        return  # queue paused

    ... run normal queue logic ...
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# How many dead-letter jobs trip the breaker
_DLQ_THRESHOLD: int = int(os.environ.get("CIRCUIT_BREAKER_DLQ_THRESHOLD", "5"))

# Jobs stuck in RUNNING longer than this are considered stale
_STALE_JOB_MINUTES: int = int(os.environ.get("STALE_JOB_MINUTES", "30"))

# Minimum seconds between DLQ count queries (avoid hitting DB on every tick)
_CHECK_INTERVAL_SECS: int = 30


class _BreakerState:
    """Internal mutable state, protected by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tripped = False
        self._last_check_at: Optional[datetime] = None
        self._last_dlq_count: int = 0
        self._manually_reset = False

    def is_tripped(self) -> bool:
        with self._lock:
            return self._tripped

    def trip(self, dlq_count: int) -> None:
        with self._lock:
            if not self._tripped:
                logger.warning(
                    "circuit_breaker.tripped dlq_count=%d threshold=%d — "
                    "serial queue paused. Call POST /api/jobs/circuit-breaker/reset to resume.",
                    dlq_count, _DLQ_THRESHOLD,
                )
            self._tripped = True

    def reset(self, actor: str = "system") -> None:
        with self._lock:
            self._tripped = False
            self._manually_reset = True
            self._last_check_at = None  # force re-check on next tick
        logger.info("circuit_breaker.reset actor=%s", actor)

    def record_check(self, dlq_count: int, now: datetime) -> None:
        with self._lock:
            self._last_check_at = now
            self._last_dlq_count = dlq_count

    def is_check_due(self, now: datetime) -> bool:
        with self._lock:
            if self._last_check_at is None:
                return True
            return (now - self._last_check_at).total_seconds() >= _CHECK_INTERVAL_SECS


_STATE = _BreakerState()


class CircuitBreaker:
    """
    Process-level circuit breaker for the pipeline queue.

    Call is_queue_healthy() at the start of run_serial_queue().
    Call reset() after resolving the underlying issues.
    """

    @staticmethod
    def is_queue_healthy(db=None) -> bool:
        """
        Return True if the queue should process work, False if it should pause.

        Performs a DB check at most every _CHECK_INTERVAL_SECS seconds.
        Pass a db session to enable DLQ checking; omit to rely on cached state.
        """
        now = datetime.now(timezone.utc)

        # If manually reset, give it one free tick before re-checking
        if _STATE.is_check_due(now) and db is not None:
            try:
                from backend.models import Job
                from backend.repositories.job_repository import JobStatus
                dlq_count = (
                    db.query(Job)
                    .filter(Job.status == JobStatus.DEAD_LETTER)
                    .count()
                )
                _STATE.record_check(dlq_count, now)
                if dlq_count >= _DLQ_THRESHOLD:
                    _STATE.trip(dlq_count)
                elif _STATE.is_tripped():
                    # DLQ was resolved without a manual reset (items re-queued/deleted)
                    _STATE.reset(actor="auto")
            except Exception as exc:
                logger.debug("CircuitBreaker: DB check failed (non-fatal): %s", exc)

        if _STATE.is_tripped():
            logger.warning(
                "circuit_breaker.queue_paused dlq_threshold=%d — resolve dead-letter jobs "
                "then call POST /api/jobs/circuit-breaker/reset",
                _DLQ_THRESHOLD,
            )
            return False
        return True

    @staticmethod
    def reset(actor: str = "operator") -> None:
        """Manually reset the circuit breaker, re-enabling the queue."""
        _STATE.reset(actor=actor)

    @staticmethod
    def status() -> dict:
        """Return current breaker status dict (for /api/metrics)."""
        return {
            "tripped": _STATE.is_tripped(),
            "dlq_threshold": _DLQ_THRESHOLD,
            "stale_job_minutes": _STALE_JOB_MINUTES,
        }


# ---------------------------------------------------------------------------
# Stale job recovery
# ---------------------------------------------------------------------------

def recover_stale_running_jobs(db) -> int:
    """
    Reset jobs stuck in RUNNING state for too long back to CREATED.

    Called once at application startup from the lifespan handler.
    Prevents jobs orphaned by a previous crash from blocking the queue forever.
    Returns the number of jobs reset.
    """
    from backend.models import Job
    from backend.repositories.job_repository import JobStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STALE_JOB_MINUTES)
    stale = (
        db.query(Job)
        .filter(
            Job.status == JobStatus.RUNNING,
            Job.started_at < cutoff,
        )
        .all()
    )
    if not stale:
        return 0

    for job in stale:
        old_worker = job.worker_id
        job.status = JobStatus.CREATED
        job.started_at = None
        job.worker_id = None
        job.error_message = (
            f"Reset from RUNNING: was started by {old_worker} and "
            f"did not finish within {_STALE_JOB_MINUTES} minutes (crash recovery)."
        )
        job.updated_at = datetime.now(timezone.utc)
        logger.warning(
            "stale_job.reset job_id=%s type=%s post_id=%s worker=%s",
            job.id, job.job_type, job.post_id, old_worker,
        )

    db.commit()
    logger.info("stale_job.recovery_complete count=%d", len(stale))
    return len(stale)
