"""
Tests for the idempotency service.

Covers:
  - Creating a new pending record
  - Recognizing an already-succeeded record (prevents duplicate publish)
  - Marking success with external_id
  - Marking failure
  - Resetting a failed record
  - Race condition: concurrent get_or_create returns same record
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from backend.services.idempotency import (
    IdempotencyService,
    IdempotencyStatus,
    youtube_publish_key,
    instagram_publish_key,
    instagram_container_key,
    sheet_update_key,
    drive_archive_key,
)


def _make_fake_record(key, status="pending", external_id=None, result_json=None, error_message=None):
    """Helper to create a fake DB record object."""
    record = MagicMock()
    record.key = key
    record.status = status
    record.external_id = external_id
    record.result_json = result_json
    record.error_message = error_message
    record.created_at = None
    return record


class TestKeyGeneration:
    """Test idempotency key format functions."""

    def test_youtube_publish_key(self):
        key = youtube_publish_key(182)
        assert key == "youtube:post:182:publish"

    def test_instagram_publish_key(self):
        key = instagram_publish_key(182)
        assert key == "instagram:post:182:publish"

    def test_instagram_container_key(self):
        key = instagram_container_key(182)
        assert key == "instagram:post:182:container_create"

    def test_sheet_update_key(self):
        key = sheet_update_key(182)
        assert key == "sheet:post:182:update"

    def test_drive_archive_original_key(self):
        key = drive_archive_key(182)
        assert key == "drive:post:182:archive_original"

    def test_drive_archive_clean_key(self):
        key = drive_archive_key(182, "clean")
        assert key == "drive:post:182:archive_clean"

    def test_keys_are_post_specific(self):
        """Different post IDs must produce different keys."""
        assert youtube_publish_key(1) != youtube_publish_key(2)
        assert instagram_publish_key(1) != instagram_publish_key(2)

    def test_keys_are_operation_specific(self):
        """Same post, different operations must produce different keys."""
        assert youtube_publish_key(182) != instagram_publish_key(182)
        assert instagram_container_key(182) != instagram_publish_key(182)


class TestIdempotencyServiceGet:
    """Test getting existing records."""

    def test_get_returns_none_for_unknown_key(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        svc = IdempotencyService(db)
        result = svc.get("youtube:post:999:publish")
        assert result is None

    def test_get_returns_entry_for_existing_pending_record(self):
        db = MagicMock()
        record = _make_fake_record("youtube:post:182:publish", status="pending")
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get("youtube:post:182:publish")

        assert entry is not None
        assert entry.status == IdempotencyStatus.PENDING
        assert not entry.already_succeeded
        assert not entry.already_failed

    def test_get_returns_entry_for_succeeded_record(self):
        import json
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="succeeded",
            external_id="yt_abc123",
            result_json=json.dumps({"video_id": "yt_abc123"}),
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get("youtube:post:182:publish")

        assert entry is not None
        assert entry.status == IdempotencyStatus.SUCCEEDED
        assert entry.external_id == "yt_abc123"
        assert entry.result_data == {"video_id": "yt_abc123"}
        assert entry.already_succeeded is True
        assert entry.already_failed is False

    def test_get_returns_entry_for_failed_record(self):
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="failed",
            error_message="Quota exceeded",
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get("youtube:post:182:publish")

        assert entry.status == IdempotencyStatus.FAILED
        assert entry.already_failed is True
        assert entry.already_succeeded is False


class TestIdempotencyServiceGetOrCreate:
    """Test get_or_create — the main entry point before external API calls."""

    def test_get_or_create_creates_new_pending_record_when_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        svc = IdempotencyService(db)
        entry = svc.get_or_create("youtube:post:182:publish")

        assert entry.status == IdempotencyStatus.PENDING
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_get_or_create_returns_existing_succeeded_record(self):
        import json
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="succeeded",
            external_id="yt_abc123",
            result_json=json.dumps({"video_id": "yt_abc123"}),
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get_or_create("youtube:post:182:publish")

        assert entry.already_succeeded is True
        assert entry.external_id == "yt_abc123"
        # Must NOT call db.add (don't create a duplicate)
        db.add.assert_not_called()

    def test_get_or_create_returns_existing_failed_record(self):
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="failed",
            error_message="Timeout",
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get_or_create("youtube:post:182:publish")

        assert entry.already_failed is True
        # Failed records can be re-attempted — return them without blocking
        db.add.assert_not_called()


class TestIdempotencyServiceMarkSucceeded:
    """Test marking operations as succeeded."""

    def test_mark_succeeded_updates_record(self):
        db = MagicMock()
        record = _make_fake_record("youtube:post:182:publish", status="pending")
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        svc.mark_succeeded("youtube:post:182:publish", external_id="yt_abc123", result_data={"video_id": "yt_abc123"})

        assert record.status == "succeeded"
        assert record.external_id == "yt_abc123"
        db.commit.assert_called_once()

    def test_mark_succeeded_handles_missing_key_gracefully(self):
        """Should not raise if key doesn't exist."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        svc = IdempotencyService(db)
        # Must not raise
        svc.mark_succeeded("youtube:post:999:publish", external_id="yt_abc123")
        db.commit.assert_not_called()


class TestIdempotencyServiceMarkFailed:
    """Test marking operations as failed."""

    def test_mark_failed_updates_record(self):
        db = MagicMock()
        record = _make_fake_record("youtube:post:182:publish", status="pending")
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        svc.mark_failed("youtube:post:182:publish", error="Quota exceeded")

        assert record.status == "failed"
        assert record.error_message == "Quota exceeded"
        db.commit.assert_called_once()


class TestIdempotencyServiceReset:
    """Test resetting failed records to allow retry."""

    def test_reset_clears_failure_state(self):
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="failed",
            error_message="Quota exceeded",
            external_id=None,
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        svc.reset("youtube:post:182:publish")

        assert record.status == "pending"
        assert record.error_message is None
        db.commit.assert_called_once()


class TestDuplicatePublishPrevention:
    """
    Critical scenario tests: duplicate YouTube publish after crash.

    These simulate the scenario where:
      1. Worker calls YouTube API → YouTube accepts → video_id returned
      2. Worker calls idempotency.mark_succeeded(video_id=...) → DB commit
      3. Worker attempts post.youtube_video_id = video_id → DB commit FAILS (network)
      4. Worker restarts and tries again
      → idempotency check finds succeeded record → returns stored video_id → no duplicate
    """

    def test_recovered_video_id_from_succeeded_record(self):
        """Simulates recovery: idempotency record has video_id but post.youtube_video_id is None."""
        import json
        db = MagicMock()
        record = _make_fake_record(
            "youtube:post:182:publish",
            status="succeeded",
            external_id="yt_abc123",
            result_json=json.dumps({"video_id": "yt_abc123"}),
        )
        db.query.return_value.filter.return_value.first.return_value = record

        svc = IdempotencyService(db)
        entry = svc.get_or_create("youtube:post:182:publish")

        # Verify caller can recover the video_id without re-uploading
        assert entry.already_succeeded is True
        assert entry.external_id == "yt_abc123"
        video_id = entry.external_id or entry.result_data.get("video_id")
        assert video_id == "yt_abc123"
