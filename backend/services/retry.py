"""
Retry system — bounded exponential backoff for external service calls.

Backoff schedule (seconds):
  attempt 1 → 0   (immediate)
  attempt 2 → 30
  attempt 3 → 120
  attempt 4 → 300
  attempt 5 → 900
  attempt > 5 → exhausted → status = failed

Permanent errors (auth, invalid input) are NOT retried.

Usage:
    from backend.services.retry import schedule_retry, is_exhausted, is_permanent_error

    try:
        do_external_call()
    except Exception as exc:
        if is_permanent_error(exc):
            mark_failed_permanently(post, db, str(exc))
        else:
            schedule_retry(post, db, str(exc))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models import Post

logger = logging.getLogger(__name__)

# Backoff in seconds indexed by attempt number (0-based: attempt 1 = index 0)
_BACKOFF_SECONDS: list[int] = [0, 30, 120, 300, 900]

# Strings that indicate a permanent / non-retryable error
_PERMANENT_ERROR_MARKERS = (
    "invalid_grant",
    "Invalid Credentials",
    "unauthorized",
    "forbidden",
    "invalid_client",
    "invalid_scope",
    "disabled_client",
    "access_denied",
    "quotaExceeded",   # YouTube daily quota — no point retrying same day
    "dailyLimitExceeded",
    "HttpError 400",
    "HttpError 401",
    "HttpError 403",
)


@dataclass
class RetryDecision:
    should_retry: bool
    backoff_seconds: int
    attempt: int
    exhausted: bool


def is_permanent_error(exc: Exception) -> bool:
    """
    Return True if this error is permanent and should not be retried.
    Permanent = auth failures, invalid input, quota exhaustion.
    """
    msg = str(exc).lower()
    return any(marker.lower() in msg for marker in _PERMANENT_ERROR_MARKERS)


def get_backoff_seconds(attempt: int) -> int:
    """Return backoff delay for this attempt number (1-based)."""
    idx = max(0, attempt - 1)
    if idx < len(_BACKOFF_SECONDS):
        return _BACKOFF_SECONDS[idx]
    return _BACKOFF_SECONDS[-1]


def schedule_retry(post: Post, db, error: str) -> RetryDecision:
    """
    Increment retry_count on post, set next_retry_at, persist to DB.
    Returns a RetryDecision describing what was scheduled.
    Does NOT mark post as 'failed' — caller decides if exhausted.
    """
    post.retry_count = (post.retry_count or 0) + 1
    post.last_error = error[:2000]  # truncate to fit column
    post.last_attempt_at = datetime.now(timezone.utc)

    max_retries = post.max_retries or 5

    if post.retry_count > max_retries:
        # Exhausted — mark failed
        post.status = "failed"
        post.error_message = f"[Exhausted after {max_retries} retries] {error}"[:2000]
        post.next_retry_at = None
        post.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.error(
            "post_id=%s retry exhausted after %d attempts: %s",
            post.id, post.retry_count, error[:200],
        )
        return RetryDecision(
            should_retry=False,
            backoff_seconds=0,
            attempt=post.retry_count,
            exhausted=True,
        )

    backoff = get_backoff_seconds(post.retry_count)
    post.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
    post.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.warning(
        "post_id=%s retry scheduled: attempt=%d/%d backoff=%ds error=%s",
        post.id, post.retry_count, max_retries, backoff, error[:200],
    )
    return RetryDecision(
        should_retry=True,
        backoff_seconds=backoff,
        attempt=post.retry_count,
        exhausted=False,
    )


def is_exhausted(post: Post) -> bool:
    """Return True if post has exceeded its max retry budget."""
    return (post.retry_count or 0) >= (post.max_retries or 5)


def clear_retry_state(post: Post, db) -> None:
    """Reset retry counters after a successful operation."""
    post.retry_count = 0
    post.next_retry_at = None
    post.last_error = None
    post.last_attempt_at = datetime.now(timezone.utc)
    post.updated_at = datetime.now(timezone.utc)
    db.commit()
