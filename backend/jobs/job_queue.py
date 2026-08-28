"""
Serial job queue — processes ONE post at a time through the pipeline.

Instead of 3+ parallel APScheduler jobs competing for resources, this single
runner ensures:
  1. Only one post is actively being processed at any moment
  2. Other posts wait in queue (ordered by created_at)
  3. Each post completes its current step before the next post starts

Priority order when picking the next post to process:
  queued   → watermark removal (clean)
  cleaned  → Gemini enrichment + YouTube upload
  uploaded → first comment

Runs every 30 seconds via APScheduler with max_instances=1.
"""
from __future__ import annotations

import logging
import threading

from backend.jobs.cleaning_job import clean_one_post, get_next_cleanable_post_id
from backend.jobs.upload_job import (
    enrich_and_upload_one_post,
    get_next_uploadable_post_id,
)
from backend.jobs.comment_job import comment_one_post, get_next_commentable_post_id

logger = logging.getLogger(__name__)

# Global lock — ensures only one job step runs at a time
_queue_lock = threading.Lock()


def run_serial_queue() -> None:
    """
    Single APScheduler entry point — processes exactly ONE step per scheduler tick.

    Each call handles the highest-priority pending post in one step, then returns.
    The 30-second scheduler interval chains steps naturally, preventing memory buildup
    and stuck jobs from blocking the queue forever.

    Priority order per tick:
      1. cleaned → enrich & schedule (fast)
      2. scheduled (no youtube_video_id) → upload to YouTube
      3. uploaded/scheduled + youtube_video_id → first comment
      4. queued → watermark removal on SSH worker (slow: 2-3 mins)
    """
    acquired = _queue_lock.acquire(blocking=False)
    if not acquired:
        logger.debug("Serial queue already running, skipping this tick")
        return

    try:
        # Priority 1: cleaned posts → enrich + schedule
        post_id = get_next_uploadable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → enrich/upload", post_id)
            enrich_and_upload_one_post(post_id)
            return

        # Priority 2: commentable posts → first comment
        post_id = get_next_commentable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → comment", post_id)
            comment_one_post(post_id)
            return

        # Priority 3: queued posts → cleaning (only when nothing else is pending)
        post_id = get_next_cleanable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → cleaning", post_id)
            clean_one_post(post_id)
            return

        logger.debug("[Queue] No actionable posts found")

    except Exception:
        logger.exception("[Queue] Unexpected error in serial queue runner")
    finally:
        _queue_lock.release()
