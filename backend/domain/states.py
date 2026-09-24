"""
Post state machine — canonical status definitions and legal transitions.

This module is the single source of truth for post lifecycle states.
All code that needs to read or transition a post status must import from here.

NEVER mutate post.status directly without going through validate_transition()
(or at minimum checking is_valid_transition()).
"""
from __future__ import annotations

from enum import Enum


class PostStatus(str, Enum):
    """Canonical post status values stored in posts.status column."""

    # Initial state — video received, not yet processed
    QUEUED = "queued"
    # Watermark removal in progress (SSH/gwr running)
    CLEANING = "cleaning"
    # Watermark removed, video ready for enrichment
    CLEANED = "cleaned"
    # Gemini enrichment + schedule slot assigned, YouTube upload pending
    SCHEDULED = "scheduled"
    # YouTube upload in progress
    UPLOADING = "uploading"
    # YouTube upload complete (has youtube_video_id)
    UPLOADED = "uploaded"
    # First comment posted (final success state for most posts)
    COMMENTED = "commented"
    # Terminal failure (may be retried)
    FAILED = "failed"
    # Manually cancelled — will not be processed further
    CANCELLED = "cancelled"


# Legal state transitions: {from_state: {set of valid to_states}}
_LEGAL_TRANSITIONS: dict[PostStatus, set[PostStatus]] = {
    PostStatus.QUEUED: {
        PostStatus.CLEANING,
        PostStatus.CLEANED,    # skip cleaning (toggle off)
        PostStatus.FAILED,
        PostStatus.CANCELLED,
    },
    PostStatus.CLEANING: {
        PostStatus.CLEANED,
        PostStatus.QUEUED,     # retry / recovery reset
        PostStatus.FAILED,
    },
    PostStatus.CLEANED: {
        PostStatus.SCHEDULED,
        PostStatus.FAILED,
    },
    PostStatus.SCHEDULED: {
        PostStatus.UPLOADING,
        PostStatus.UPLOADED,   # direct skip (already has video_id)
        PostStatus.QUEUED,     # retry reset
        PostStatus.FAILED,
        PostStatus.CANCELLED,
    },
    PostStatus.UPLOADING: {
        PostStatus.UPLOADED,
        PostStatus.SCHEDULED,  # upload failed, back to scheduled to retry
        PostStatus.FAILED,
    },
    PostStatus.UPLOADED: {
        PostStatus.COMMENTED,
        PostStatus.FAILED,
    },
    PostStatus.COMMENTED: {
        PostStatus.FAILED,     # very rare — allows re-processing
    },
    PostStatus.FAILED: {
        PostStatus.QUEUED,     # manual or automatic retry
        PostStatus.CANCELLED,
    },
    PostStatus.CANCELLED: set(),  # terminal
}


class InvalidTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""

    def __init__(
        self,
        from_state: PostStatus | str,
        to_state: PostStatus | str,
        post_id: int | None = None,
    ) -> None:
        msg = f"Invalid transition: {from_state!r} → {to_state!r}"
        if post_id is not None:
            msg = f"Post {post_id}: {msg}"
        super().__init__(msg)
        self.from_state = from_state
        self.to_state = to_state
        self.post_id = post_id


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """Return True if the transition from_status → to_status is allowed."""
    try:
        from_s = PostStatus(from_status)
        to_s = PostStatus(to_status)
    except ValueError:
        return False
    return to_s in _LEGAL_TRANSITIONS.get(from_s, set())


def validate_transition(
    from_status: str,
    to_status: str,
    post_id: int | None = None,
) -> None:
    """
    Raise InvalidTransitionError if the transition is not allowed.
    Use this at all state-mutation sites.
    """
    if not is_valid_transition(from_status, to_status):
        raise InvalidTransitionError(from_status, to_status, post_id)


def terminal_states() -> set[str]:
    """Return the set of terminal status values (no further processing)."""
    return {PostStatus.COMMENTED.value, PostStatus.CANCELLED.value}


def active_states() -> set[str]:
    """Return status values that represent an in-flight post."""
    return {
        PostStatus.CLEANING.value,
        PostStatus.UPLOADING.value,
    }


def retryable_states() -> set[str]:
    """Return status values that can be re-queued for retry."""
    return {PostStatus.FAILED.value}
