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
    Single APScheduler entry point — picks the highest-priority actionable
    post and runs exactly one pipeline step for it.

    Because APScheduler is configured with max_instances=1 and we also hold
    _queue_lock, at most one invocation runs at a time even if a step takes
    longer than the 30-second interval.
    """
    acquired = _queue_lock.acquire(blocking=False)
    if not acquired:
        logger.debug("Serial queue already running, skipping this tick")
        return

    try:
        # Priority 1: queued posts → cleaning
        post_id = get_next_cleanable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → cleaning", post_id)
            clean_one_post(post_id)
            return

        # Priority 2: cleaned / due-scheduled posts → enrich + upload
        post_id = get_next_uploadable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → enrich/upload", post_id)
            enrich_and_upload_one_post(post_id)
            return

        # Priority 3: uploaded posts → first comment
        post_id = get_next_commentable_post_id()
        if post_id:
            logger.info("[Queue] Processing post %s → comment", post_id)
            comment_one_post(post_id)
            return

        # Nothing to do
        logger.debug("[Queue] No actionable posts found")

    except Exception:
        logger.exception("[Queue] Unexpected error in serial queue runner")
    finally:
        _queue_lock.release()
