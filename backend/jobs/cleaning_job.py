"""APScheduler job — pick up queued posts and run watermark removal."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from backend.database import SessionLocal
from backend.models import Post
from backend.services.watermark import remove_watermark

logger = logging.getLogger(__name__)

# Guard against concurrent cleaning of the same post
_in_progress: set[int] = set()
_lock = threading.Lock()


def clean_one_post(post_id: int) -> None:
    """
    Run watermark removal for a single post (blocking).
    Called by the serial job queue runner.
    """
    with _lock:
        if post_id in _in_progress:
            logger.debug("Post %s already being cleaned, skipping", post_id)
            return
        _in_progress.add(post_id)

    try:
        logger.info("Starting watermark removal for post %s", post_id)
        remove_watermark(post_id)
        logger.info("Watermark removal complete for post %s", post_id)
    finally:
        with _lock:
            _in_progress.discard(post_id)


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

        post = (
            db.query(Post.id)
            .filter(Post.status == "queued")
            .order_by(Post.created_at.asc())
            .first()
        )
        return post.id if post else None
    finally:
        db.close()


def run_cleaning_job() -> None:
    """Legacy entry point — cleans the next queued post (single, blocking)."""
    post_id = get_next_cleanable_post_id()
    if post_id:
        clean_one_post(post_id)
