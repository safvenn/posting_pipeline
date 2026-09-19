"""Tests — retry system (services/retry.py)."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _make_post(retry_count=0, max_retries=5, status="queued"):
    """Create a minimal mock Post."""
    post = MagicMock()
    post.id = 42
    post.retry_count = retry_count
    post.max_retries = max_retries
    post.status = status
    post.next_retry_at = None
    post.last_error = None
    post.last_attempt_at = None
    post.error_message = None
    post.updated_at = None
    return post


def _make_db():
    db = MagicMock()
    db.commit = MagicMock()
    return db


class TestRetrySystem:
    def test_first_retry_immediate(self):
        from backend.services.retry import schedule_retry
        post = _make_post(retry_count=0)
        db = _make_db()
        decision = schedule_retry(post, db, "connection error")
        assert decision.should_retry is True
        # attempt=1 → get_backoff_seconds(1) → index 0 → 0s (immediate first retry)
        assert decision.backoff_seconds == 0
        assert decision.exhausted is False
        assert post.retry_count == 1

    def test_backoff_increases(self):
        from backend.services.retry import schedule_retry, get_backoff_seconds
        assert get_backoff_seconds(1) == 0    # immediate on first
        assert get_backoff_seconds(2) == 30
        assert get_backoff_seconds(3) == 120
        assert get_backoff_seconds(4) == 300
        assert get_backoff_seconds(5) == 900

    def test_exhausted_marks_failed(self):
        from backend.services.retry import schedule_retry
        post = _make_post(retry_count=5, max_retries=5)
        db = _make_db()
        decision = schedule_retry(post, db, "persistent error")
        assert decision.exhausted is True
        assert decision.should_retry is False
        assert post.status == "failed"
        assert "Exhausted" in post.error_message

    def test_permanent_error_detection(self):
        from backend.services.retry import is_permanent_error
        assert is_permanent_error(Exception("invalid_grant")) is True
        assert is_permanent_error(Exception("Invalid Credentials")) is True
        assert is_permanent_error(Exception("HttpError 403")) is True
        assert is_permanent_error(Exception("quotaExceeded")) is True
        assert is_permanent_error(Exception("connection timeout")) is False
        assert is_permanent_error(Exception("503 Service Unavailable")) is False
        assert is_permanent_error(Exception("network error")) is False

    def test_clear_retry_state(self):
        from backend.services.retry import clear_retry_state
        post = _make_post(retry_count=3)
        post.next_retry_at = datetime.now(timezone.utc)
        post.last_error = "some error"
        db = _make_db()
        clear_retry_state(post, db)
        assert post.retry_count == 0
        assert post.next_retry_at is None
        assert post.last_error is None

    def test_retry_count_increments(self):
        from backend.services.retry import schedule_retry
        post = _make_post(retry_count=2)
        db = _make_db()
        decision = schedule_retry(post, db, "timeout")
        assert post.retry_count == 3
        assert decision.attempt == 3
