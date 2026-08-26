"""
APScheduler job — post the first comment after a video goes public.

Rules (from production n8n pipeline, baked in):
  - Wait 3 minutes AFTER publishAt before attempting (YouTube private→public flip lags).
  - Retry up to 4 times, 5 seconds apart.
  - If all retries fail: set first_comment_posted=False but status stays 'uploaded'.
    The video is already live — comment failure must NOT fail the post.
  - Quota errors (403/429) are logged distinctly and treated as retriable.

Channel isolation: each channel processed in its own try/except.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post
from backend.services.youtube_auth import (
    get_youtube_client,
    is_quota_error,
    quota_error_message,
)

logger = logging.getLogger(__name__)

COMMENT_BUFFER_MINUTES = 3    # wait after publishAt before trying
MAX_RETRIES = 4
RETRY_DELAY_SECONDS = 5


def _post_comment(yt, video_id: str, comment_text: str) -> None:
    """Call YouTube commentThreads.insert. Raises on failure."""
    yt.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": comment_text}
                },
            }
        },
    ).execute()


def _try_post_comment(post: Post, db) -> bool:
    """
    Attempt to post the first comment with retries.
    Returns True on success, False if all retries exhausted.
    """
    video_id = post.youtube_video_id
    comment_text = post.first_comment_text or "What did you think? Let me know! 👇"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            yt = get_youtube_client(post.channel)
            _post_comment(yt, video_id, comment_text)
            logger.info("First comment posted for post %s (attempt %d)", post.id, attempt)
            return True

        except Exception as exc:
            if is_quota_error(exc):
                logger.warning(
                    "Quota error posting comment for post %s (attempt %d): %s",
                    post.id, attempt, exc,
                )
                # Quota errors: no point retrying rapidly, stop here
                return False
            else:
                logger.warning(
                    "Comment attempt %d/%d failed for post %s: %s",
                    attempt, MAX_RETRIES, post.id, exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

    return False


def comment_one_post(post_id: int) -> None:
    """
    Post the first comment on a single uploaded post (blocking).
    Called by the serial job queue runner.
    """
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if not post:
            logger.warning("Post %s not found for commenting", post_id)
            return

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=COMMENT_BUFFER_MINUTES)

        # Verify post is ready for commenting
        if post.status != "uploaded" or post.first_comment_posted:
            return
        if not post.youtube_video_id or not post.scheduled_at:
            return
        if post.scheduled_at + buffer > now:
            logger.debug("Post %s not ready for comment yet (buffer not elapsed)", post_id)
            return

        success = _try_post_comment(post, db)
        post.first_comment_posted = success
        if success:
            post.status = "commented"
            post.error_message = None
        else:
            # Keep status=uploaded, video is live and that matters more
            existing_err = post.error_message or ""
            if "comment" not in existing_err:
                post.error_message = (
                    (existing_err + " | " if existing_err else "") +
                    "first comment failed after all retries"
                )
        post.updated_at = now
        db.commit()
        logger.info("Comment job for post %s complete (success=%s)", post_id, success)

    except Exception:
        logger.exception("Unexpected error in comment job for post %s", post_id)
        db.rollback()
    finally:
        db.close()


def get_next_commentable_post_id() -> int | None:
    """Return the ID of the oldest uploaded post ready for commenting, or None."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=COMMENT_BUFFER_MINUTES)

        post = (
            db.query(Post.id)
            .filter(
                Post.status == "uploaded",
                Post.first_comment_posted == False,
                Post.youtube_video_id.isnot(None),
                Post.scheduled_at.isnot(None),
                Post.scheduled_at + buffer <= now,
            )
            .order_by(Post.scheduled_at.asc())
            .first()
        )
        return post.id if post else None
    finally:
        db.close()


def run_comment_job() -> None:
    """Legacy APScheduler entry point — runs every 60 seconds."""
    post_id = get_next_commentable_post_id()
    if post_id:
        comment_one_post(post_id)

