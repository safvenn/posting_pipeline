"""
Workflow event logger — structured audit trail for every pipeline step.

Every call inserts a WorkflowEvent row AND emits a structured log line.
Identifiers (post_id, drive_file_id, youtube_video_id, sheet_row_id, etc.)
are included in every log line for easy grep / log aggregation.

NEVER log: access tokens, refresh tokens, passwords, API keys, secrets.

Usage:
    from backend.services.workflow_logger import wlog

    wlog(
        db,
        post_id=post.id,
        event_type="YOUTUBE_UPLOAD_COMPLETED",
        status="success",
        message="Uploaded successfully",
        youtube_video_id=video_id,
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("workflow")

# Canonical event type constants
VIDEO_RECEIVED = "VIDEO_RECEIVED"
DRIVE_UPLOAD_STARTED = "DRIVE_UPLOAD_STARTED"
DRIVE_UPLOAD_COMPLETED = "DRIVE_UPLOAD_COMPLETED"
DRIVE_UPLOAD_FAILED = "DRIVE_UPLOAD_FAILED"
CLEANING_STARTED = "CLEANING_STARTED"
CLEANING_COMPLETED = "CLEANING_COMPLETED"
ENRICHMENT_COMPLETED = "ENRICHMENT_COMPLETED"
SCHEDULE_ASSIGNED = "SCHEDULE_ASSIGNED"
YOUTUBE_UPLOAD_STARTED = "YOUTUBE_UPLOAD_STARTED"
YOUTUBE_UPLOAD_COMPLETED = "YOUTUBE_UPLOAD_COMPLETED"
SHEET_UPDATED = "SHEET_UPDATED"
SHEET_UPDATE_FAILED = "SHEET_UPDATE_FAILED"
INSTAGRAM_PUBLISH_STARTED = "INSTAGRAM_PUBLISH_STARTED"
INSTAGRAM_PUBLISHED = "INSTAGRAM_PUBLISHED"
FAILED = "FAILED"
RETRY_SCHEDULED = "RETRY_SCHEDULED"


def wlog(
    db,
    *,
    post_id: Optional[int],
    event_type: str,
    status: str = "info",   # info | success | failure | retry
    attempt: int = 1,
    message: Optional[str] = None,
    drive_file_id: Optional[str] = None,
    youtube_video_id: Optional[str] = None,
    sheet_row_id: Optional[str] = None,
    instagram_container_id: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Insert a WorkflowEvent row and emit a structured log line.
    Best-effort — any DB error is caught and logged; never raises.
    """
    # Build metadata dict (no secrets)
    meta: dict[str, Any] = {}
    if drive_file_id:
        meta["drive_file_id"] = drive_file_id
    if youtube_video_id:
        meta["youtube_video_id"] = youtube_video_id
    if sheet_row_id:
        meta["sheet_row_id"] = sheet_row_id
    if instagram_container_id:
        meta["instagram_container_id"] = instagram_container_id
    if extra:
        meta.update(extra)

    metadata_json = json.dumps(meta) if meta else None

    # Structured log line — includes all identifiers for grep/aggregation
    log_parts = [f"event={event_type}", f"status={status}", f"attempt={attempt}"]
    if post_id is not None:
        log_parts.insert(0, f"post_id={post_id}")
    if drive_file_id:
        log_parts.append(f"drive_file_id={drive_file_id}")
    if youtube_video_id:
        log_parts.append(f"youtube_video_id={youtube_video_id}")
    if sheet_row_id:
        log_parts.append(f"sheet_row_id={sheet_row_id}")
    if message:
        log_parts.append(f"msg={message[:200]}")

    log_line = " ".join(log_parts)
    if status == "failure":
        logger.error(log_line)
    elif status == "retry":
        logger.warning(log_line)
    else:
        logger.info(log_line)

    # DB insert
    try:
        from backend.models import WorkflowEvent
        event = WorkflowEvent(
            post_id=post_id,
            event_type=event_type,
            status=status,
            attempt=attempt,
            message=(message or "")[:2000] if message else None,
            metadata_json=metadata_json,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
    except Exception as exc:
        logger.warning("WorkflowEvent insert failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
