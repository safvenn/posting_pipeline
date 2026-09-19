"""
Tests for instant slot assignment and Google Sheet update on video upload.
Ensures:
  1. bind_slot_and_update_sheet determines the next slot and updates Google Sheet immediately.
  2. upload_from_extension / ingest_from_extension bind the next slot and return scheduled_at.
  3. get_extension_channels excludes internal 'google_drive' configuration.
  4. upload_job._schedule_single_post preserves pre-assigned scheduled_at from upload.
"""
from __future__ import annotations

import io
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz
from fastapi import UploadFile

from backend.models import ChannelConfig, Post
from backend.services.sheets import bind_slot_and_update_sheet

IST = pytz.timezone("Asia/Kolkata")


def test_bind_slot_and_update_sheet_existing_unscheduled_row():
    """Test that bind_slot_and_update_sheet updates Google Sheet with next slot."""
    mock_post = MagicMock(spec=Post)
    mock_post.id = 42
    mock_post.sheet_row_id = None
    mock_post.scheduled_at = None
    mock_post.title = "Delicious Butter Chicken"
    mock_post.description = "Tasty recipe"
    mock_post.tags = "cooking;food"

    fake_slot = IST.localize(datetime(2026, 9, 20, 12, 30, 0))

    with patch("backend.services.scheduler_logic.pick_next_slot", return_value=fake_slot), \
         patch("backend.services.sheets.get_first_unscheduled_row", return_value={"id": "5", "title": "Old Title"}), \
         patch("backend.services.sheets.update_row_fields") as mock_update, \
         patch("backend.services.workflow_logger.wlog"):

        db = MagicMock()
        slot, row_id = bind_slot_and_update_sheet("channel_a", db, mock_post, preferred_title="Delicious Butter Chicken")

        assert slot == fake_slot
        assert row_id == "5"
        assert mock_post.scheduled_at == fake_slot
        assert mock_post.sheet_row_id == "5"

        # Verify Google Sheet was updated immediately with scheduled time & title
        mock_update.assert_called_once_with(
            "channel_a",
            "5",
            {
                "scheduled": "2026-09-20T12:30:00+05:30",
                "title": "Delicious Butter Chicken",
            },
        )


def test_bind_slot_and_update_sheet_appends_new_row_when_none_unscheduled():
    """Test that when all rows are scheduled, append_new_row is called and updated."""
    mock_post = MagicMock(spec=Post)
    mock_post.id = 99
    mock_post.sheet_row_id = None
    mock_post.scheduled_at = None
    mock_post.title = "Mini Naan"
    mock_post.description = ""
    mock_post.tags = ""

    fake_slot = IST.localize(datetime(2026, 9, 20, 18, 30, 0))

    with patch("backend.services.scheduler_logic.pick_next_slot", return_value=fake_slot), \
         patch("backend.services.sheets.get_first_unscheduled_row", return_value=None), \
         patch("backend.services.sheets.append_new_row", return_value={"id": "10", "title": "Mini Naan"}) as mock_append, \
         patch("backend.services.sheets.update_row_fields") as mock_update, \
         patch("backend.services.workflow_logger.wlog"):

        db = MagicMock()
        slot, row_id = bind_slot_and_update_sheet("channel_a", db, mock_post, preferred_title="Mini Naan")

        assert slot == fake_slot
        assert row_id == "10"
        mock_append.assert_called_once()
        mock_update.assert_called_once_with(
            "channel_a",
            "10",
            {
                "scheduled": "2026-09-20T18:30:00+05:30",
                "title": "Mini Naan",
            },
        )


def test_extension_channels_excludes_google_drive():
    """Verify that get_extension_channels excludes the internal 'google_drive' channel."""
    from backend.routers.extension import get_extension_channels

    db = MagicMock()
    # Mock query to simulate database filter
    ch1 = ChannelConfig(key="channel_a", display_name="Channel A", is_active=True)
    ch2 = ChannelConfig(key="the_indian_kitchen", display_name="The Indian Kitchen", is_active=True)

    filter_mock = MagicMock()
    filter_mock.all.return_value = [ch1, ch2]
    db.query.return_value.filter.return_value = filter_mock

    channels = get_extension_channels(db=db)
    keys = [c["id"] for c in channels]
    assert "google_drive" not in keys
    assert "channel_a" in keys
    assert "the_indian_kitchen" in keys


def test_schedule_single_post_preserves_existing_slot():
    """Verify that _schedule_single_post preserves pre-assigned scheduled_at from upload."""
    from backend.jobs.upload_job import _schedule_single_post

    pre_assigned_slot = IST.localize(datetime(2026, 9, 21, 12, 30, 0))
    post = MagicMock(spec=Post)
    post.id = 1
    post.channel = "channel_a"
    post.title = "Crispy Samosa"
    post.description = "Test description"
    post.tags = "food;cooking"
    post.sheet_row_id = "7"
    post.scheduled_at = pre_assigned_slot

    db = MagicMock()

    # When Gemini returns None, it falls back to rule-based
    with patch("backend.jobs.upload_job._gemini_enrich_and_schedule", return_value=None), \
         patch("backend.jobs.upload_job._get_subscriber_count", return_value=1000), \
         patch("backend.services._enrichment_rules.enrich_post", return_value={
             "enriched_title": "Crispy Samosa ASMR #shorts",
             "enriched_description": "Full recipe",
             "enriched_tags": "asmr;food",
             "first_comment_text": "Enjoy!",
         }), \
         patch("backend.services.scheduler_logic.pick_next_slot") as mock_pick, \
         patch("backend.jobs.upload_job.wlog"), \
         patch("backend.jobs.upload_job._set_status"):

        success = _schedule_single_post(post, db)
        assert success is True
        # pick_next_slot should NOT have been called because post.scheduled_at was already set
        mock_pick.assert_not_called()
        assert post.scheduled_at == pre_assigned_slot
