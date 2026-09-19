"""APScheduler job — pick up queued posts and run watermark removal.

Pipeline step order per post:
  1. Drive upload (archive original) — if not already done
  2. SSH watermark cleaning
  3. Delete local original after both confirmed

Uses retry system for Drive upload failures.
Watermark SSH failure resets to queued for retry by scheduler.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post
from backend.services.storage import get_storage
from backend.services.retry import schedule_retry, is_permanent_error
from backend.services.workflow_logger import (
    wlog,
    DRIVE_UPLOAD_STARTED,
    DRIVE_UPLOAD_COMPLETED,
    DRIVE_UPLOAD_FAILED,
    CLEANING_STARTED,
    CLEANING_COMPLETED,
    RETRY_SCHEDULED,
)

logger = logging.getLogger(__name__)

# Guard against concurrent cleaning of the same post
_in_progress: set[int] = set()
_lock = threading.Lock()


def _do_drive_upload(post: Post, db) -> bool:
    """
    Upload original video to Google Drive (Indian Kitchen folder).
    Returns True on success, False on failure (retry scheduled).
    Idempotent: skips if drive_upload_status == 'completed'.
    """
    if post.drive_upload_status == "completed":
        return True

    folder_id = settings.google_drive_indian_kitchen_folder_id
    if not folder_id:
        # Drive not configured — log warning and proceed without Drive
        logger.warning(
            "post_id=%s GOOGLE_DRIVE_INDIAN_KITCHEN_FOLDER_ID not set — skipping Drive upload",
            post.id,
        )
        post.drive_upload_status = "completed"  # treat as satisfied
        db.commit()
        return True

    video_path = Path(post.video_path)
    if not video_path.exists():
        logger.error("post_id=%s Drive upload skipped: video file missing %s", post.id, video_path)
        return False

    # Mark as pending before attempting
    post.drive_upload_status = "pending"
    post.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        dest_name = f"post_{post.id}_{video_path.name}"
        wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_STARTED, status="info",
             message=f"Uploading {dest_name} to Drive folder {folder_id}")

        storage = get_storage()
        file_id = storage.upload(video_path, dest_name=dest_name, folder_id=folder_id)

        post.drive_file_id = file_id
        post.drive_upload_status = "completed"
        post.updated_at = datetime.now(timezone.utc)
        db.commit()

        wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_COMPLETED, status="success",
             drive_file_id=file_id, message=f"Drive upload complete: {dest_name}")
        logger.info("post_id=%s Drive upload done drive_file_id=%s", post.id, file_id)
        return True

    except Exception as exc:
        err = str(exc)
        wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_FAILED, status="failure",
             message=err[:500], attempt=post.retry_count + 1)

        if is_permanent_error(exc):
            logger.error("post_id=%s Drive upload permanent error — skipping Drive: %s", post.id, err)
            # Don't block the pipeline on Drive if it's a permanent auth failure
            post.drive_upload_status = "failed"
            post.last_error = err[:2000]
            post.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True  # continue pipeline — Drive archive failure is non-blocking

        decision = schedule_retry(post, db, err)
        wlog(db, post_id=post.id, event_type=RETRY_SCHEDULED, status="retry",
             attempt=decision.attempt, message=f"backoff={decision.backoff_seconds}s")
        return False  # caller will re-queue


def clean_one_post(post_id: int) -> None:
    """
    Start watermark removal for a single post in a BACKGROUND THREAD.

    The SSH + gwr pipeline takes 2-5 minutes. Running it inside the serial
    queue lock would block all other pipeline steps (enrich/upload/comment)
    for the entire duration. Instead we:
      1. Drive upload original (if configured)
      2. Mark the post as in-progress (under lock)
      3. Spawn a daemon thread and release the lock immediately
      4. The thread calls remove_watermark() which handles all status updates

    Called by the serial job queue runner.
    """
    with _lock:
        if post_id in _in_progress:
            logger.debug("Post %s already being cleaned, skipping", post_id)
            return
        _in_progress.add(post_id)

    def _run():
        db = SessionLocal()
        try:
            post = db.get(Post, post_id)
            if not post:
                logger.warning("[Cleaning] Post %s not found", post_id)
                return

            # Step 1: Drive upload original (before destructive SSH processing)
            drive_ok = _do_drive_upload(post, db)
            if not drive_ok:
                logger.warning(
                    "[Cleaning] post_id=%s Drive upload failed — deferring cleaning", post_id
                )
                # Reset to queued so retry picks it up
                post.status = "queued"
                post.updated_at = datetime.now(timezone.utc)
                db.commit()
                return

            # Step 2: SSH watermark removal
            from backend.services.watermark import remove_watermark
            logger.info("[Cleaning] Starting watermark removal for post %s", post_id)
            wlog(db, post_id=post_id, event_type=CLEANING_STARTED, status="info")

            remove_watermark(post_id)

            # Re-fetch to check final status
            db.expire(post)
            post = db.get(Post, post_id)
            if post and post.status == "cleaned":
                wlog(db, post_id=post_id, event_type=CLEANING_COMPLETED, status="success")
                logger.info("[Cleaning] Watermark removal complete for post %s", post_id)
            else:
                status_now = post.status if post else "unknown"
                logger.warning("[Cleaning] Post %s ended with status=%s", post_id, status_now)

        except Exception:
            logger.exception("[Cleaning] Unexpected error for post %s", post_id)
        finally:
            db.close()
            with _lock:
                _in_progress.discard(post_id)

    t = threading.Thread(target=_run, name=f"clean-post-{post_id}", daemon=True)
    t.start()
    logger.info("[Cleaning] Spawned background thread for post %s", post_id)


def get_next_cleanable_post_id() -> int | None:
    """Return the ID of the oldest cleanable post (queued or orphaned cleaning), or None."""
    db = SessionLocal()
    try:
        with _lock:
            active_ids = set(_in_progress)

        # Automatically recover any post stuck in 'cleaning' that is NOT currently being processed
        orphans = db.query(Post).filter(Post.status == "cleaning").all()
        orphans_recovered = False
        for p in orphans:
            if p.id not in active_ids:
                logger.warning("Found orphaned cleaning post %s, resetting to queued", p.id)
                p.status = "queued"
                p.updated_at = datetime.now(timezone.utc)
                orphans_recovered = True

        if orphans_recovered:
            db.commit()

        # Don't pick a new post if one is actively being cleaned
        # (avoid spawning multiple expensive SSH connections)
        if active_ids:
            logger.debug("[Cleaning] %d post(s) currently being cleaned, waiting: %s", len(active_ids), active_ids)
            return None

        # Also pick up posts due for retry (next_retry_at <= now and status queued or failed-retryable)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        retry_post = (
            db.query(Post.id)
            .filter(
                Post.status == "queued",
                Post.next_retry_at.isnot(None),
                Post.next_retry_at <= now,
                Post.retry_count < Post.max_retries,
            )
            .order_by(Post.next_retry_at.asc())
            .first()
        )
        if retry_post:
            return retry_post.id

        post = (
            db.query(Post.id)
            .filter(
                Post.status == "queued",
                Post.next_retry_at.is_(None),  # not waiting for retry backoff
            )
            .order_by(Post.created_at.asc())
            .first()
        )
        if not post:
            return None

        # Pre-flight: check SSH is configured before picking the post
        if not settings.worker_ssh_host or not settings.worker_ssh_host.strip():
            logger.error(
                "[Cleaning] WORKER_SSH_HOST is not configured — post %s cannot be cleaned. "
                "Set WORKER_SSH_HOST in Render environment variables.",
                post.id,
            )
            p = db.get(Post, post.id)
            if p and p.status == "queued":
                p.status = "failed"
                p.error_message = "WORKER_SSH_HOST not configured. Set it in Render environment variables."
                p.updated_at = datetime.now(timezone.utc)
                db.commit()
            return None

        # Pre-flight: check video file still exists on disk
        p = db.get(Post, post.id)
        if p:
            video_path = p.video_path
            if not video_path or not Path(video_path).exists():
                # If Drive upload succeeded, video was archived — mark failed (file gone from disk)
                logger.error(
                    "[Cleaning] Post %s video file not found: %s — marking failed",
                    post.id, video_path,
                )
                p.status = "failed"
                p.error_message = (
                    f"Video file not found on server: {video_path}. "
                    "The file may have been lost after a server restart (Render ephemeral disk). "
                    "Please re-upload the video."
                )
                p.updated_at = datetime.now(timezone.utc)
                db.commit()
                return None

        return post.id
    finally:
        db.close()


def run_cleaning_job() -> None:
    """Legacy entry point — cleans the next queued post (single, blocking)."""
    post_id = get_next_cleanable_post_id()
    if post_id:
        clean_one_post(post_id)
