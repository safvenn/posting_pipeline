"""
Serial job queue — processes ONE post at a time through the pipeline.

Instead of 3+ parallel APScheduler jobs competing for resources, this single
runner ensures:
  1. Only one post is actively being processed at any moment
  2. Other posts wait in queue (ordered by created_at)
  3. Each post completes its current step before the next post starts

Priority order when picking the next post to process:
  queued   → watermark removal (clean)      [slow: SSH 2-5 min, background thread]
  cleaned  → Gemini enrichment + schedule   [fast: 5-15s, in-tick]
  scheduled (no video_id) → YouTube upload  [slow: 1-3 min, background thread]
  uploaded → first comment                  [fast]
  uploaded → Instagram Reel publishing      [fast, time-gated]

Runs every 30 seconds via APScheduler with max_instances=1.
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

logger = logging.getLogger(__name__)

# Global lock — ensures only one job step runs at a time
_queue_lock = threading.Lock()

# Track which posts are currently uploading to YouTube (background)
_uploading: set[int] = set()
_uploading_lock = threading.Lock()


def run_serial_queue() -> None:
    """
    Single APScheduler entry point — processes exactly ONE step per scheduler tick.

    Priority order (re-ordered to prevent queued starvation):
      1. queued  → watermark cleaning (background SSH thread)
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
        # Priority 1: queued → cleaning (spawns background SSH thread, returns fast)
        post_id = get_next_cleanable_post_id()
        if post_id:
            logger.info("[Queue] Post %s → cleaning (background SSH)", post_id)
            clean_one_post(post_id)
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
            with _uploading_lock:
                if post_id in _uploading:
                    logger.debug("[Queue] Post %s already uploading, skip", post_id)
                else:
                    _uploading.add(post_id)
                    logger.info("[Queue] Post %s → YouTube upload (background)", post_id)

                    def _run_upload(pid=post_id):
                        try:
                            upload_one_post(pid)
                        finally:
                            with _uploading_lock:
                                _uploading.discard(pid)

                    threading.Thread(target=_run_upload, name=f"upload-{post_id}", daemon=True).start()
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
