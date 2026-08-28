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
    Start watermark removal for a single post in a BACKGROUND THREAD.

    The SSH + gwr pipeline takes 2-5 minutes. Running it inside the serial
    queue lock would block all other pipeline steps (enrich/upload/comment)
    for the entire duration. Instead we:
      1. Mark the post as in-progress (under lock)
      2. Spawn a daemon thread and release the lock immediately
      3. The thread calls remove_watermark() which handles all status updates

    Called by the serial job queue runner.
    """
    with _lock:
        if post_id in _in_progress:
            logger.debug("Post %s already being cleaned, skipping", post_id)
            return
        _in_progress.add(post_id)

    def _run():
        try:
            logger.info("[Cleaning] Starting watermark removal for post %s", post_id)
            remove_watermark(post_id)
            logger.info("[Cleaning] Watermark removal complete for post %s", post_id)
        finally:
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

        post = (
            db.query(Post.id)
            .filter(Post.status == "queued")
            .order_by(Post.created_at.asc())
            .first()
        )
        if not post:
            return None

        # Pre-flight: check SSH is configured before picking the post
        from backend.config import settings
        if not settings.worker_ssh_host or not settings.worker_ssh_host.strip():
            logger.error(
                "[Cleaning] WORKER_SSH_HOST is not configured — post %s cannot be cleaned. "
                "Set WORKER_SSH_HOST in Render environment variables.",
                post.id,
            )
            # Mark this post as failed immediately with a clear error
            p = db.get(Post, post.id)
            if p and p.status == "queued":
                p.status = "failed"
                p.error_message = "WORKER_SSH_HOST not configured. Set it in Render environment variables."
                p.updated_at = datetime.now(timezone.utc)
                db.commit()
            return None

        # Pre-flight: check video file still exists on disk
        from pathlib import Path
        p = db.get(Post, post.id)
        if p:
            video_path = p.video_path
            if not video_path or not Path(video_path).exists():
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
