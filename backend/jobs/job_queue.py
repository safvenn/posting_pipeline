"""
Serial job queue — processes ONE post at a time through the pipeline.

Instead of 3+ parallel APScheduler jobs competing for resources, this single
runner ensures:
  1. Only one post is actively being processed at any moment
  2. Other posts wait in queue (ordered by created_at)
  3. Each post completes its current step before the next post starts

Priority order when picking the next post to process:
  queued   → watermark removal (clean)      [slow: SSH 2-5 min, background thread]
             OR skip to cleaned if clean_watermark_enabled=False
  cleaned  → Gemini enrichment + schedule   [fast: 5-15s, in-tick]
  scheduled (no video_id) → YouTube upload  [slow: 1-3 min, background thread]
  uploaded → first comment                  [fast]
  uploaded → Instagram Reel publishing      [fast, time-gated]

Runs every 30 seconds via APScheduler with max_instances=1.

Phase 3 changes:
  - All post selector queries delegated to PostRepository
  - Orphan recovery in get_next_cleanable_post_id moved to PostRepository
  - job_queue.py contains ONLY orchestration logic (no raw DB queries)
"""
from __future__ import annotations

import logging
import threading

from backend.jobs.cleaning_job import clean_one_post, get_next_cleanable_post_id
from backend.jobs.upload_job import (
    enrich_one_post,
    upload_one_post,
    get_next_enrichable_post_id,
    get_next_uploadable_post_id,
)
from backend.jobs.comment_job import comment_one_post, get_next_commentable_post_id
from backend.jobs.instagram_job import (
    publish_instagram_for_post,
    get_next_instagram_publishable_post_id,
)
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Global lock — ensures only one job step runs at a time
_queue_lock = threading.Lock()

# Track which posts are currently uploading to YouTube (background)
_uploading: set[int] = set()
_uploading_lock = threading.Lock()


def _is_watermark_cleaning_enabled() -> bool:
    """Return True if watermark cleaning is enabled in app settings.

    Reads from the database each tick so toggle changes take effect on the next
    scheduler run without requiring a server restart.
    Defaults to True if the row is missing or an error occurs.
    """
    try:
        from backend.database import SessionLocal
        from backend.routers.settings import get_clean_watermark_enabled
        with SessionLocal() as db:
            return get_clean_watermark_enabled(db)
    except Exception:
        logger.exception("[Queue] Failed to read clean_watermark_enabled setting, defaulting to True")
        return True


def _skip_cleaning_for_post(post_id: int) -> None:
    """Advance a queued post directly to 'cleaned' status, bypassing watermark SSH.

    Used when clean_watermark_enabled is False — the original video is used as-is
    for enrichment and YouTube upload (no watermark removal performed).
    Records the skip as a CLEAN Job (succeeded, 0ms).
    """
    from backend.database import SessionLocal
    from backend.services.job_tracker import JobTracker
    from backend.repositories.job_repository import JobType

    with JobTracker(post_id, JobType.CLEAN, input_data={"post_id": post_id, "skipped": True}) as tracker:
        db = SessionLocal()
        try:
            from backend.models import Post
            post = db.query(Post).filter(Post.id == post_id, Post.status == "queued").first()
            if post is None:
                logger.warning("[Queue] Skip-cleaning: post %s not found or no longer queued", post_id)
                return
            # Re-use the original video path as the cleaned path so the enrich step
            # has a valid file to work with.
            post.clean_video_path = post.clean_video_path or post.video_path
            post.status = "cleaned"
            db.commit()
            tracker.set_output({"status": "cleaned", "skipped_watermark": True})
            logger.info(
                "[Queue] Post %s: watermark cleaning SKIPPED (toggle OFF) — advanced to cleaned",
                post_id,
            )
        except Exception:
            logger.exception("[Queue] Error skipping cleaning for post %s", post_id)
            raise
        finally:
            db.close()


def run_serial_queue() -> None:
    """
    Single APScheduler entry point — processes exactly ONE step per scheduler tick.

    Priority order (re-ordered to prevent queued starvation):
      1. queued  → watermark cleaning (background SSH thread)
                   OR direct-skip to cleaned if clean_watermark_enabled=False
      2. cleaned → Gemini enrich + schedule slot (fast, in-tick)
      3. scheduled (no video_id) → YouTube upload (background thread)
      4. uploaded/scheduled + video_id → first comment
      5. scheduled/commented (past publishAt) → Instagram

    Slow operations (cleaning, YouTube upload) run in daemon threads so the
    lock is released immediately, preventing starvation of other pipeline steps.
    """
    acquired = _queue_lock.acquire(blocking=False)
    if not acquired:
        logger.debug("Serial queue already running, skipping this tick")
        return

    try:
        # Circuit breaker: pause queue if too many dead-letter jobs
        from backend.database import SessionLocal as _SL
        _cb_db = _SL()
        try:
            if not CircuitBreaker.is_queue_healthy(db=_cb_db):
                return  # queue is paused — breaker tripped
        finally:
            _cb_db.close()

        # Priority 1: queued → cleaning (or direct-skip if toggle is OFF)
        post_id = get_next_cleanable_post_id()
        if post_id:
            cleaning_enabled = _is_watermark_cleaning_enabled()
            if cleaning_enabled:
                logger.info("[Queue] Post %s → cleaning (background SSH)", post_id)
                clean_one_post(post_id)
            else:
                logger.info(
                    "[Queue] Post %s → skip cleaning (toggle OFF), advancing to cleaned",
                    post_id,
                )
                _skip_cleaning_for_post(post_id)
            return

        # Priority 2: cleaned → enrich + schedule (fast Gemini call, in-tick)
        post_id = get_next_enrichable_post_id()
        if post_id:
            logger.info("[Queue] Post %s → enrich + schedule", post_id)
            enrich_one_post(post_id)
            return

        # Priority 3: scheduled (no video_id) → YouTube upload (background thread)
        post_id = get_next_uploadable_post_id()
        if post_id:
            spawned = False
            with _uploading_lock:
                if post_id in _uploading:
                    logger.debug("[Queue] Post %s already uploading, skip to next priority", post_id)
                else:
                    _uploading.add(post_id)
                    spawned = True
                    logger.info("[Queue] Post %s → YouTube upload (background)", post_id)

                    def _run_upload(pid=post_id):
                        try:
                            upload_one_post(pid)
                        finally:
                            with _uploading_lock:
                                _uploading.discard(pid)

                    threading.Thread(target=_run_upload, name=f"upload-{post_id}", daemon=True).start()
            if spawned:
                return

        # Priority 4: comment
        post_id = get_next_commentable_post_id()
        if post_id:
            logger.info("[Queue] Post %s → comment", post_id)
            comment_one_post(post_id)
            return

        # Priority 5: Instagram (time-gated)
        post_id = get_next_instagram_publishable_post_id()
        if post_id:
            logger.info("[Queue] Post %s → Instagram Reel publish", post_id)
            publish_instagram_for_post(post_id)
            return

        logger.debug("[Queue] No actionable posts found")

    except Exception:
        logger.exception("[Queue] Unexpected error in serial queue runner")
    finally:
        _queue_lock.release()
