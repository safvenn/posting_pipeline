"""
Instagram Scheduled Publishing Job

Logic:
  - Runs every 30s via the APScheduler serial queue
  - Finds posts where:
      1. instagram_enabled is True for the channel
      2. post is 'scheduled' and has a youtube_video_id
      3. scheduled_at has passed (video is now live on YouTube)
      4. instagram_status is 'none' or 'failed' (not yet published / retry)
  - Waits for YouTube publish time + 3 min buffer (so YT is truly public first)
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


def get_next_instagram_publishable_post_id() -> int | None:
    """
    Return the ID of the oldest post that:
      - has instagram_enabled = True for its channel
      - has youtube_video_id (was uploaded to YouTube)
      - has scheduled_at that has passed the buffer window
      - has instagram_status in ('none', 'failed') meaning not yet published
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)

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

        post = (
            db.query(Post.id)
            .filter(
                Post.channel.in_(ig_channels),
                Post.status.in_(["scheduled", "commented"]),
                Post.youtube_video_id.isnot(None),
                Post.scheduled_at.isnot(None),
                Post.scheduled_at + buffer <= now,
                Post.instagram_status.in_(["none", "failed"]),
                # Exclude posts that already have a published Instagram URL
                Post.instagram_media_id.is_(None),
            )
            .order_by(Post.scheduled_at.asc())
            .first()
        )
        return post.id if post else None
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
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)

        if not post.youtube_video_id:
            logger.debug("[Instagram] Post %s has no YouTube video ID yet, skipping", post_id)
            return

        if not post.scheduled_at:
            logger.debug("[Instagram] Post %s has no scheduled_at, skipping", post_id)
            return

        if post.scheduled_at + buffer > now:
            logger.debug(
                "[Instagram] Post %s not ready yet — YouTube goes public at %s, buffer ends at %s (now: %s)",
                post_id,
                post.scheduled_at.strftime("%H:%M UTC"),
                (post.scheduled_at + buffer).strftime("%H:%M UTC"),
                now.strftime("%H:%M UTC"),
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
