"""
Metrics router — operational observability endpoint.

GET /api/metrics
  Returns a JSON snapshot of the current system state useful for:
  - Render dashboard custom metrics
  - External monitoring (UptimeRobot, Better Uptime, Grafana)
  - Frontend dashboard widgets

Metrics included:
  pipeline_queue:
    - queued_count         posts waiting to start
    - cleaning_count       posts currently being watermark-cleaned (SSH)
    - cleaned_count        posts awaiting Gemini enrichment
    - scheduled_count      posts scheduled, not yet uploaded to YouTube
    - uploading_count      posts currently uploading to YouTube (background threads)
    - uploaded_count       posts uploaded, awaiting comment / Instagram
    - commented_count      posts with first comment posted
    - failed_count         posts in failed state
    - total_posts          sum of all post statuses

  job_execution:
    - running_count        jobs currently in RUNNING state
    - succeeded_24h        jobs that succeeded in the last 24 hours
    - failed_24h           jobs that failed in the last 24 hours
    - dead_letter_count    jobs in dead_letter state (require manual action)
    - p50_duration_ms      median job duration (last 24h) per job type
    - p95_duration_ms      95th percentile job duration (last 24h) per job type

  auth:
    - active_sessions      non-revoked, non-expired refresh tokens

  system:
    - uptime_seconds       seconds since application startup
    - collected_at         ISO-8601 UTC timestamp of this snapshot
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from backend.database import get_db
from backend.models import Job, Post, RefreshToken
from backend.repositories.job_repository import JobStatus

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# Record startup time
_STARTUP_TIME = time.monotonic()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class PipelineQueueMetrics(BaseModel):
    queued_count: int
    cleaning_count: int
    cleaned_count: int
    scheduled_count: int
    uploaded_count: int
    commented_count: int
    failed_count: int
    total_posts: int


class PerTypeLatency(BaseModel):
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    sample_count: int


class JobExecutionMetrics(BaseModel):
    running_count: int
    succeeded_24h: int
    failed_24h: int
    dead_letter_count: int
    latency_by_type: dict[str, PerTypeLatency]


class AuthMetrics(BaseModel):
    active_sessions: int


class SystemMetrics(BaseModel):
    uptime_seconds: float
    collected_at: str


class MetricsResponse(BaseModel):
    pipeline_queue: PipelineQueueMetrics
    job_execution: JobExecutionMetrics
    auth: AuthMetrics
    system: SystemMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(values: list[float], p: float) -> Optional[float]:
    """Return the p-th percentile of values, or None if empty."""
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = (p / 100) * (len(sorted_vals) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = idx - lower
    return round(sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac, 1)


def _pipeline_queue_metrics(db: Session) -> PipelineQueueMetrics:
    """Count posts by status in a single query."""
    rows = (
        db.query(Post.status, func.count(Post.id))
        .group_by(Post.status)
        .all()
    )
    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    total = sum(counts.values())
    return PipelineQueueMetrics(
        queued_count=counts.get("queued", 0),
        cleaning_count=counts.get("cleaning", 0),
        cleaned_count=counts.get("cleaned", 0),
        scheduled_count=counts.get("scheduled", 0),
        uploaded_count=counts.get("uploaded", 0),
        commented_count=counts.get("commented", 0),
        failed_count=counts.get("failed", 0),
        total_posts=total,
    )


def _job_execution_metrics(db: Session) -> JobExecutionMetrics:
    """Job counts and per-type latency percentiles for the last 24h."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    # Running / dead-letter counts (all time)
    running = (
        db.query(func.count(Job.id))
        .filter(Job.status == JobStatus.RUNNING)
        .scalar() or 0
    )
    dead_letter = (
        db.query(func.count(Job.id))
        .filter(Job.status == JobStatus.DEAD_LETTER)
        .scalar() or 0
    )

    # 24h success / failure counts
    succeeded_24h = (
        db.query(func.count(Job.id))
        .filter(Job.status == JobStatus.SUCCEEDED, Job.finished_at >= since)
        .scalar() or 0
    )
    failed_24h = (
        db.query(func.count(Job.id))
        .filter(Job.status == JobStatus.FAILED, Job.finished_at >= since)
        .scalar() or 0
    )

    # Latency by type (last 24h, succeeded only, duration_ms not null)
    latency_rows = (
        db.query(Job.job_type, Job.duration_ms)
        .filter(
            Job.status == JobStatus.SUCCEEDED,
            Job.finished_at >= since,
            Job.duration_ms.isnot(None),
        )
        .all()
    )

    # Group by type
    by_type: dict[str, list[float]] = {}
    for job_type, duration_ms in latency_rows:
        by_type.setdefault(job_type, []).append(float(duration_ms))

    latency_by_type = {
        jtype: PerTypeLatency(
            p50_ms=_percentile(vals, 50),
            p95_ms=_percentile(vals, 95),
            sample_count=len(vals),
        )
        for jtype, vals in by_type.items()
    }

    return JobExecutionMetrics(
        running_count=running,
        succeeded_24h=succeeded_24h,
        failed_24h=failed_24h,
        dead_letter_count=dead_letter,
        latency_by_type=latency_by_type,
    )


def _auth_metrics(db: Session) -> AuthMetrics:
    """Count active (non-revoked, non-expired) refresh token sessions."""
    now = datetime.now(timezone.utc)
    active = (
        db.query(func.count(RefreshToken.id))
        .filter(
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .scalar() or 0
    )
    return AuthMetrics(active_sessions=active)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)):
    """
    Return a structured JSON metrics snapshot.

    All metrics are computed in a single request — no caching.
    For high-frequency polling, add a Redis cache layer in front
    (Phase 6 — External Cache).
    """
    return MetricsResponse(
        pipeline_queue=_pipeline_queue_metrics(db),
        job_execution=_job_execution_metrics(db),
        auth=_auth_metrics(db),
        system=SystemMetrics(
            uptime_seconds=round(time.monotonic() - _STARTUP_TIME, 1),
            collected_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        ),
    )
