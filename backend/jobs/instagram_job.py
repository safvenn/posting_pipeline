"""
Instagram Scheduled Publishing Job

Logic:
  - Runs every 30s via the APScheduler serial queue
  - Finds posts where:
      1. instagram_enabled is True for the channel
      2. post is 'scheduled' or 'commented' and has a youtube_video_id
      3. scheduled_at has passed (video is now live on YouTube)
      4. instagram_status is 'none', 'container_ready', or 'failed' (not yet published / retry)
  - Waits for YouTube publish time + 5 min buffer (so YT is truly public first)
  - Then publishes the Reel via Instagram Graph API

This ensures Instagram posts at the SAME time as YouTube goes public.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models import ChannelConfig, Post

logger = logging.getLogger(__name__)

# How long after YouTube publishAt to wait before posting to Instagram
# YouTube has a ~1-2 min private→public flip delay; 5 min is safe
INSTAGRAM_PUBLISH_BUFFER_MINUTES = 5

# Max retry attempts for failed Instagram posts
MAX_INSTAGRAM_RETRIES = 3


def _to_utc_aware(dt: datetime) -> datetime:
    """
    Normalize any datetime to UTC-aware.
    SQLite stores datetimes without timezone info (naive UTC), so we must
    treat naive datetimes as UTC before comparing with timezone.utc datetimes.
    """
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_next_instagram_publishable_post_id() -> int | None:
    """
    Return the ID of the oldest post that:
      - has instagram_enabled = True for its channel
      - has youtube_video_id (was uploaded to YouTube)
      - has scheduled_at that has passed the buffer window
      - has instagram_status in ('none', 'container_ready', 'failed') meaning not yet published
    """
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)
        retry_delay = timedelta(minutes=15)

        # Get all Instagram-enabled channel keys
        ig_channels = [
            c.key for c in db.query(ChannelConfig)
            .filter(
                ChannelConfig.instagram_enabled == True,
                ChannelConfig.instagram_account_id.isnot(None),
                ChannelConfig.instagram_access_token.isnot(None),
            ).all()
        ]
        if not ig_channels:
            return None

        # Fetch candidate posts and do timezone-safe comparison in Python
        # (avoids SQLite naive vs UTC-aware comparison TypeError)
        from sqlalchemy import or_, and_
        candidates = (
            db.query(Post)
            .filter(
                Post.channel.in_(ig_channels),
                Post.status.in_(["scheduled", "commented"]),
                Post.youtube_video_id.isnot(None),
                Post.scheduled_at.isnot(None),
                Post.instagram_media_id.is_(None),
                or_(
                    Post.instagram_status == "none",
                    Post.instagram_status == "container_ready",
                    and_(
                        Post.instagram_status == "failed",
                        Post.instagram_media_id.is_(None),
                    ),
                ),
            )
            .order_by(Post.scheduled_at.asc())
            .all()
        )

        for post in candidates:
            # Normalize scheduled_at to UTC-aware (SQLite returns naive UTC)
            sched_utc = _to_utc_aware(post.scheduled_at)
            if sched_utc is None:
                continue

            # Check buffer: scheduled_at + buffer must be in the past
            if sched_utc + buffer > now_utc:
                continue

            # For failed posts: check retry delay
            if post.instagram_status == "failed":
                updated_utc = _to_utc_aware(post.updated_at)
                if updated_utc and updated_utc + retry_delay > now_utc:
                    continue

            return post.id

        return None
    finally:
        db.close()


def publish_instagram_for_post(post_id: int) -> None:
    """
    Trigger Instagram Reels publishing for a single post at its scheduled time.
    Called by the serial job queue runner.
    """
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if not post:
            logger.warning("[Instagram] Post %s not found", post_id)
            return

        # Double-check post is eligible
        now_utc = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)

        if not post.youtube_video_id:
            logger.debug("[Instagram] Post %s has no YouTube video ID yet, skipping", post_id)
            return

        if not post.scheduled_at:
            logger.debug("[Instagram] Post %s has no scheduled_at, skipping", post_id)
            return

        # Normalize to UTC-aware (SQLite stores naive UTC datetimes)
        sched_utc = _to_utc_aware(post.scheduled_at)

        if sched_utc + buffer > now_utc:
            logger.debug(
                "[Instagram] Post %s not ready yet — YouTube goes public at %s UTC, buffer ends at %s UTC (now: %s UTC)",
                post_id,
                sched_utc.strftime("%H:%M"),
                (sched_utc + buffer).strftime("%H:%M"),
                now_utc.strftime("%H:%M"),
            )
            return

        if post.instagram_status == "published" or post.instagram_media_id:
            logger.debug("[Instagram] Post %s already published to Instagram, skipping", post_id)
            return

        logger.info(
            "[Instagram] Publishing Reel for post %s (channel=%s, scheduled_at=%s, YT=%s)",
            post_id, post.channel,
            post.scheduled_at.strftime("%Y-%m-%d %H:%M UTC"),
            post.youtube_video_id,
        )

        from backend.services.instagram import publish_reel_for_post
        result = publish_reel_for_post(post, db)

        if result.get("success"):
            logger.info(
                "[Instagram] ✓ Reel published for post %s: %s",
                post_id, result.get("permalink"),
            )
        elif result.get("skipped"):
            logger.debug("[Instagram] Post %s skipped: %s", post_id, result.get("reason"))
        else:
            logger.warning(
                "[Instagram] ✗ Reel publishing failed for post %s: %s",
                post_id, result.get("error"),
            )

    except Exception:
        logger.exception("[Instagram] Unexpected error publishing Reel for post %s", post_id)
    finally:
        db.close()


def run_instagram_publish_job() -> None:
    """
    Legacy / standalone entry point — publishes one due Instagram post per call.
    Also called by the APScheduler for dedicated Instagram triggering.
    """
    post_id = get_next_instagram_publishable_post_id()
    if post_id:
        publish_instagram_for_post(post_id)
    else:
        logger.debug("[Instagram] No posts due for Instagram publishing right now")
