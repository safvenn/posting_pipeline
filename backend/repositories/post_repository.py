"""
Post Repository — data access layer for the posts table.

Centralizes all query logic for Post. Replaces scattered db.query(Post)
calls that appear in job_queue.py, cleaning_job.py, upload_job.py,
instagram_job.py, and multiple routers.

Key benefits:
  - Single place to add indexes, query hints, or caching
  - All filtering through canonical PostStatus enum (no string literals)
  - Supports future sharding/partitioning without touching business logic
  - Testable in isolation

Usage:
    from backend.repositories.post_repository import PostRepository

    repo = PostRepository(db)
    next_post = repo.next_for_cleaning()
    repo.transition(post, "cleaning")
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.domain.states import PostStatus, validate_transition
from backend.models import Post

logger = logging.getLogger(__name__)


class PostRepository:
    """Data access for the posts table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Core lookups
    # ------------------------------------------------------------------

    def get(self, post_id: int) -> Optional[Post]:
        return self._db.get(Post, post_id)

    def get_or_raise(self, post_id: int) -> Post:
        post = self.get(post_id)
        if post is None:
            from backend.domain.errors import NotFoundError
            raise NotFoundError(f"Post {post_id} not found")
        return post

    def list_by_status(
        self,
        status: str | PostStatus,
        channel: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Post]:
        status_val = status.value if isinstance(status, PostStatus) else status
        q = self._db.query(Post).filter(Post.status == status_val)
        if channel:
            q = q.filter(Post.channel == channel)
        return q.order_by(Post.created_at.asc()).offset(offset).limit(limit).all()

    def count_by_status(self, status: str | PostStatus) -> int:
        status_val = status.value if isinstance(status, PostStatus) else status
        return self._db.query(Post).filter(Post.status == status_val).count()

    # ------------------------------------------------------------------
    # Queue selectors — used by job_queue.py
    # ------------------------------------------------------------------

    def next_for_cleaning(self, exclude_ids: set[int] | None = None) -> Optional[Post]:
        """
        Return the oldest queued post eligible for watermark cleaning.
        Excludes posts already in-progress (passed via exclude_ids set).
        """
        now = datetime.now(timezone.utc)
        exclude_ids = exclude_ids or set()

        # Priority 1: queued posts due for retry
        retry_q = (
            self._db.query(Post)
            .filter(
                Post.status == PostStatus.QUEUED.value,
                Post.next_retry_at.isnot(None),
                Post.next_retry_at <= now,
                Post.retry_count < Post.max_retries,
            )
            .order_by(Post.next_retry_at.asc())
        )
        if exclude_ids:
            retry_q = retry_q.filter(Post.id.notin_(exclude_ids))
        post = retry_q.first()
        if post:
            return post

        # Priority 2: normal queued posts (not waiting for retry backoff)
        q = (
            self._db.query(Post)
            .filter(
                Post.status == PostStatus.QUEUED.value,
                Post.next_retry_at.is_(None),
            )
            .order_by(Post.created_at.asc())
        )
        if exclude_ids:
            q = q.filter(Post.id.notin_(exclude_ids))
        return q.first()

    def next_for_enrichment(self) -> Optional[Post]:
        """Return the oldest cleaned post ready for Gemini enrichment."""
        return (
            self._db.query(Post)
            .filter(Post.status == PostStatus.CLEANED.value)
            .order_by(Post.created_at.asc())
            .first()
        )

    def next_for_upload(self, exclude_ids: set[int] | None = None) -> Optional[Post]:
        """
        Return the oldest scheduled post without a YouTube video_id
        that is ready to upload.
        """
        exclude_ids = exclude_ids or set()
        q = (
            self._db.query(Post)
            .filter(
                Post.status == PostStatus.SCHEDULED.value,
                Post.youtube_video_id.is_(None),
            )
            .order_by(Post.scheduled_at.asc().nullslast(), Post.created_at.asc())
        )
        if exclude_ids:
            q = q.filter(Post.id.notin_(exclude_ids))
        return q.first()

    def next_for_comment(self) -> Optional[Post]:
        """Return the oldest uploaded post still needing a first comment."""
        return (
            self._db.query(Post)
            .filter(
                Post.status == PostStatus.UPLOADED.value,
                Post.youtube_video_id.isnot(None),
            )
            .order_by(Post.created_at.asc())
            .first()
        )

    def next_for_instagram(self, ig_channels: list[str]) -> Optional[Post]:
        """
        Return the oldest post ready for Instagram publishing.
        Only returns posts whose YouTube publish time has passed + buffer.
        """
        from datetime import timedelta
        from sqlalchemy import or_, and_

        if not ig_channels:
            return None

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=5)

        candidates = (
            self._db.query(Post)
            .filter(
                Post.channel.in_(ig_channels),
                Post.status.in_([PostStatus.SCHEDULED.value, PostStatus.COMMENTED.value]),
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
            sched_utc = post.scheduled_at
            if sched_utc is None:
                continue
            # Normalize naive datetimes to UTC
            if sched_utc.tzinfo is None:
                sched_utc = sched_utc.replace(tzinfo=timezone.utc)
            if sched_utc + buffer > now:
                continue
            # For failed posts: check 15-min retry delay
            if post.instagram_status == "failed":
                updated = post.updated_at
                if updated:
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    if updated + timedelta(minutes=15) > now:
                        continue
            return post
        return None

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def transition(
        self,
        post: Post,
        new_status: str | PostStatus,
        *,
        commit: bool = True,
        actor: str = "system",
    ) -> Post:
        """
        Transition a post to a new status, enforcing the state machine.

        Raises InvalidTransitionError for illegal transitions.
        Updates updated_at automatically.
        """
        new_val = new_status.value if isinstance(new_status, PostStatus) else new_status
        old_val = post.status
        validate_transition(old_val, new_val, post_id=post.id)

        post.status = new_val
        post.updated_at = datetime.now(timezone.utc)

        if commit:
            self._db.commit()
            logger.info(
                "post.transition post_id=%s %s → %s actor=%s",
                post.id, old_val, new_val, actor,
            )
        return post

    # ------------------------------------------------------------------
    # Startup recovery
    # ------------------------------------------------------------------

    def reset_orphaned_cleaning(self, active_ids: set[int]) -> int:
        """
        Reset posts stuck in 'cleaning' that are NOT in active_ids.
        Returns count reset.
        """
        orphans = (
            self._db.query(Post)
            .filter(Post.status == PostStatus.CLEANING.value)
            .all()
        )
        reset_count = 0
        for p in orphans:
            if p.id not in active_ids:
                p.status = PostStatus.QUEUED.value
                p.updated_at = datetime.now(timezone.utc)
                reset_count += 1
        if reset_count:
            self._db.commit()
        return reset_count

    def reset_orphaned_uploading(self, active_ids: set[int]) -> int:
        """
        Reset posts stuck in 'uploading' that are NOT in active_ids.
        Returns count reset.
        """
        orphans = (
            self._db.query(Post)
            .filter(Post.status == PostStatus.UPLOADING.value)
            .all()
        )
        reset_count = 0
        for p in orphans:
            if p.id not in active_ids:
                p.status = PostStatus.SCHEDULED.value
                p.updated_at = datetime.now(timezone.utc)
                reset_count += 1
        if reset_count:
            self._db.commit()
        return reset_count

    # ------------------------------------------------------------------
    # Status summary (for health/dashboard)
    # ------------------------------------------------------------------

    def status_counts(self) -> dict[str, int]:
        """Return a dict of {status: count} for all statuses."""
        from sqlalchemy import func
        rows = (
            self._db.query(Post.status, func.count(Post.id))
            .group_by(Post.status)
            .all()
        )
        return {row[0]: row[1] for row in rows}
