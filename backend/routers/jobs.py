"""
Jobs router — visibility into pipeline execution history + fault recovery.

Endpoints (all require api-key auth):
  GET  /api/jobs                          — paginated list (filterable by status, type, post_id)
  GET  /api/jobs/stats                    — aggregated counts by status and type
  GET  /api/jobs/running                  — currently running jobs
  GET  /api/jobs/dead-letters             — jobs in dead_letter state
  GET  /api/jobs/circuit-breaker/status   — circuit breaker state
  POST /api/jobs/circuit-breaker/reset    — manually re-enable paused queue
  POST /api/jobs/requeue-all-dead-letters — bulk retry all DLQ jobs
  GET  /api/jobs/{job_id}                 — single job detail
  POST /api/jobs/{job_id}/retry           — re-queue a failed/dead-letter job
  POST /api/jobs/{job_id}/cancel          — cancel a non-terminal job
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Job
from backend.repositories.job_repository import JobRepository, JobStatus, JobType
from backend.schemas_pagination import PaginationParams, PaginatedResponse, paginate, pagination_params
from backend.services.audit import AuditService, SystemEvent

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class JobResponse(BaseModel):
    id: int
    post_id: Optional[int]
    job_type: str
    status: str
    attempt: int
    worker_id: Optional[str]
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    error_message: Optional[str]
    external_ref: Optional[str]
    output: Optional[dict]
    created_at: datetime
    is_terminal: bool
    elapsed_seconds: Optional[float]

    class Config:
        from_attributes = True


class JobStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    running_count: int
    dead_letter_count: int
    failed_last_hour: int


class CircuitBreakerStatusResponse(BaseModel):
    tripped: bool
    dlq_threshold: int
    stale_job_minutes: int
    message: str


class BulkRequeueResponse(BaseModel):
    requeued_count: int
    job_ids: list[int]


class ClaimJobRequest(BaseModel):
    worker_id: str
    supported_types: Optional[list[str]] = None


class HeartbeatRequest(BaseModel):
    worker_id: str


class ReleaseJobRequest(BaseModel):
    worker_id: str
    reason: Optional[str] = "graceful_shutdown"


class ReapStaleResponse(BaseModel):
    reaped_total: int
    reclaimed_count: int
    reclaimed_ids: list[int]
    dead_letter_count: int
    dead_letter_ids: list[int]


class ActiveWorkerResponse(BaseModel):
    worker_id: str
    active_jobs: int
    last_heartbeat: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job_to_response(job: Job) -> JobResponse:
    output = None
    if job.output_json:
        try:
            output = json.loads(job.output_json)
        except Exception:
            output = {"raw": job.output_json}
    return JobResponse(
        id=job.id,
        post_id=job.post_id,
        job_type=job.job_type,
        status=job.status,
        attempt=job.attempt,
        worker_id=job.worker_id,
        scheduled_at=job.scheduled_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
        error_message=job.error_message,
        external_ref=job.external_ref,
        output=output,
        created_at=job.created_at,
        is_terminal=job.is_terminal,
        elapsed_seconds=job.elapsed_seconds,
    )


def _get_job_or_404(job_id: int, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    pagination: PaginationParams = Depends(pagination_params),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by job status"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    post_id: Optional[int] = Query(None, description="Filter by post ID"),
):
    """List jobs with optional filtering. Newest first."""
    q = db.query(Job)
    if status_filter:
        q = q.filter(Job.status == status_filter)
    if job_type:
        q = q.filter(Job.job_type == job_type)
    if post_id is not None:
        q = q.filter(Job.post_id == post_id)
    q = q.order_by(Job.created_at.desc())

    result = paginate(q, pagination)
    result["items"] = [_job_to_response(j) for j in result["items"]]
    return result


@router.get("/stats", response_model=JobStatsResponse)
def job_stats(db: Session = Depends(get_db)):
    """Return aggregate job counts by status and type."""
    from sqlalchemy import func
    from datetime import timedelta

    status_rows = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    by_status = {row[0]: row[1] for row in status_rows}

    type_rows = db.query(Job.job_type, func.count(Job.id)).group_by(Job.job_type).all()
    by_type = {row[0]: row[1] for row in type_rows}

    total = sum(by_status.values())
    running = by_status.get(JobStatus.RUNNING, 0)
    dead_letter = by_status.get(JobStatus.DEAD_LETTER, 0)

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    failed_last_hour = (
        db.query(func.count(Job.id))
        .filter(Job.status == JobStatus.FAILED, Job.finished_at >= hour_ago)
        .scalar()
        or 0
    )

    return JobStatsResponse(
        total=total,
        by_status=by_status,
        by_type=by_type,
        running_count=running,
        dead_letter_count=dead_letter,
        failed_last_hour=failed_last_hour,
    )


@router.get("/running", response_model=list[JobResponse])
def running_jobs(db: Session = Depends(get_db)):
    """Return all currently running jobs."""
    repo = JobRepository(db)
    jobs = repo.list_running()
    return [_job_to_response(j) for j in jobs]


@router.get("/dead-letters", response_model=list[JobResponse])
def dead_letter_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Return jobs in dead-letter state requiring manual intervention."""
    repo = JobRepository(db)
    jobs = repo.list_dead_letters(limit=limit)
    return [_job_to_response(j) for j in jobs]


# ---------------------------------------------------------------------------
# Circuit breaker routes  (MUST be before /{job_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/circuit-breaker/status", response_model=CircuitBreakerStatusResponse)
def circuit_breaker_status():
    """Return the current circuit breaker state."""
    from backend.services.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker.status()
    tripped = cb["tripped"]
    return CircuitBreakerStatusResponse(
        **cb,
        message=(
            "Queue is PAUSED — too many dead-letter jobs. "
            "Resolve them and call POST /api/jobs/circuit-breaker/reset to resume."
            if tripped else
            "Queue is operating normally."
        ),
    )


@router.post("/circuit-breaker/reset")
def reset_circuit_breaker(
    db: Session = Depends(get_db),
    actor: str = Query("operator", description="Who is resetting (for audit log)"),
):
    """
    Manually reset the circuit breaker to resume queue processing.

    Use this after resolving dead-letter jobs that caused the breaker to trip.
    """
    from backend.services.circuit_breaker import CircuitBreaker
    audit = AuditService(db, actor=actor)
    CircuitBreaker.reset(actor=actor)
    audit.log(
        SystemEvent.CIRCUIT_BREAKER_RESET,
        description=f"Circuit breaker manually reset by {actor}",
    )
    return {
        "detail": "Circuit breaker reset. Queue will resume on the next scheduler tick.",
        "actor": actor,
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/requeue-all-dead-letters", response_model=BulkRequeueResponse)
def requeue_all_dead_letters(
    db: Session = Depends(get_db),
    actor: str = Query("operator", description="Who is re-queueing"),
    confirm: bool = Query(False, description="Must be true to execute"),
):
    """
    Re-queue ALL dead-letter jobs for retry.

    Requires ?confirm=true to prevent accidental bulk operations.
    Also resets the circuit breaker so the queue resumes immediately.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass ?confirm=true to execute bulk re-queue",
        )

    repo = JobRepository(db)
    dead_jobs = repo.list_dead_letters(limit=500)
    requeued_ids = []
    for job in dead_jobs:
        repo.requeue(job, actor=actor)
        requeued_ids.append(job.id)

    # Reset breaker so queue resumes immediately
    from backend.services.circuit_breaker import CircuitBreaker
    CircuitBreaker.reset(actor=actor)

    audit = AuditService(db, actor=actor)
    audit.log(
        SystemEvent.BULK_REQUEUE,
        description=f"Bulk re-queued {len(requeued_ids)} dead-letter jobs",
    )

    return BulkRequeueResponse(requeued_count=len(requeued_ids), job_ids=requeued_ids)


# ---------------------------------------------------------------------------
# Distributed worker coordination & leasing endpoints
# ---------------------------------------------------------------------------

@router.post("/claim", response_model=Optional[JobResponse])
def claim_job(
    req: ClaimJobRequest,
    db: Session = Depends(get_db),
):
    """
    Atomically lease the next scheduled job for a worker.
    Uses SELECT ... FOR UPDATE SKIP LOCKED (Postgres) or atomic transaction (SQLite).
    """
    from backend.services.worker_coordinator import WorkerCoordinator
    coordinator = WorkerCoordinator(db)
    job = coordinator.claim_next_job(
        worker_id=req.worker_id,
        supported_types=req.supported_types,
    )
    if not job:
        return None
    return _job_to_response(job)


@router.post("/reap-stale", response_model=ReapStaleResponse)
def reap_stale_jobs(
    stale_seconds: int = Query(600, ge=10, le=86400),
    max_attempts: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Detect and recover zombie jobs from dead/unresponsive workers."""
    from backend.services.worker_coordinator import WorkerCoordinator
    coordinator = WorkerCoordinator(db)
    result = coordinator.reap_stale_leases(
        stale_threshold_seconds=stale_seconds,
        max_attempts=max_attempts,
    )
    return ReapStaleResponse(**result)


@router.get("/active-workers", response_model=list[ActiveWorkerResponse])
def list_active_workers(
    active_seconds: int = Query(300, ge=10, le=86400),
    db: Session = Depends(get_db),
):
    """List cluster workers currently processing jobs."""
    from backend.services.worker_coordinator import WorkerCoordinator
    coordinator = WorkerCoordinator(db)
    return [
        ActiveWorkerResponse(**w)
        for w in coordinator.list_active_workers(active_seconds=active_seconds)
    ]


# ---------------------------------------------------------------------------
# Single job detail + mutation routes  (MUST be after named routes above)
# ---------------------------------------------------------------------------

@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Return a single job by ID."""
    return _job_to_response(_get_job_or_404(job_id, db))


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    actor: str = Query("operator", description="Who is retrying (for audit log)"),
):
    """
    Re-queue a FAILED or DEAD_LETTER job for another attempt.

    The job is reset to CREATED state. The serial queue will pick it up
    on the next scheduler tick and execute it again with the same inputs.

    Only FAILED and DEAD_LETTER jobs can be retried. Running/succeeded/cancelled
    jobs are rejected with 422.
    """
    job = _get_job_or_404(job_id, db)
    repo = JobRepository(db)

    try:
        repo.requeue(job, actor=actor)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    audit = AuditService(db, actor=actor)
    audit.log(
        SystemEvent.JOB_RETRY,
        resource_type="job",
        resource_id=str(job_id),
        description=f"Job {job_id} ({job.job_type}) re-queued by {actor} (attempt {job.attempt})",
    )

    return _job_to_response(job)


@router.post("/{job_id}/heartbeat")
def heartbeat_job(
    job_id: int,
    req: HeartbeatRequest,
    db: Session = Depends(get_db),
):
    """Refresh the lease timestamp for a running job to prevent zombie reaping."""
    from backend.services.worker_coordinator import WorkerCoordinator
    coordinator = WorkerCoordinator(db)
    refreshed = coordinator.heartbeat(job_id=job_id, worker_id=req.worker_id)
    if not refreshed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} lease lost or owned by another worker",
        )
    return {"status": "ok", "job_id": job_id, "refreshed": True}


@router.post("/{job_id}/release")
def release_job(
    job_id: int,
    req: ReleaseJobRequest,
    db: Session = Depends(get_db),
):
    """Voluntarily release a job back to the queue (graceful worker shutdown)."""
    from backend.services.worker_coordinator import WorkerCoordinator
    coordinator = WorkerCoordinator(db)
    released = coordinator.release_job(job_id=job_id, worker_id=req.worker_id, reason=req.reason or "graceful_shutdown")
    if not released:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} not in RUNNING state or not owned by {req.worker_id}",
        )
    return {"status": "ok", "job_id": job_id, "released": True}
