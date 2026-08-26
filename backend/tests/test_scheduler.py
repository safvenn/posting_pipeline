"""Unit tests for pick_next_slot() scheduling logic."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytz
import pytest

IST = pytz.timezone("Asia/Kolkata")


def _ist_at(hour, minute=0) -> datetime:
    """Return today at the given hour:minute in IST (always naive-then-localize)."""
    now_ist = datetime.now(IST)
    return IST.localize(datetime(now_ist.year, now_ist.month, now_ist.day, hour, minute, 0))


# ---- Isolate pick_next_slot from YouTube API and DB ----------------------- #

@pytest.fixture(autouse=True)
def mock_externals(monkeypatch):
    """Patch out YouTube API and DB calls so tests run offline."""
    import backend.services.scheduler_logic as sl

    monkeypatch.setattr(sl, "_get_channel_video_count", lambda ch: 50)
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: [])


# ---- Basic: returns a future slot ----------------------------------------- #

def test_returns_future_slot():
    from backend.services.scheduler_logic import pick_next_slot

    now = datetime.now(IST)
    slot = pick_next_slot("channel_a", db=MagicMock())
    assert slot > now, "Returned slot must be strictly in the future"
    assert slot.tzinfo is not None, "Slot must be timezone-aware"


# ---- Slot A (12:30) and Slot B (18:30) are the only options ------------- #

def test_slot_is_1230_or_1830(monkeypatch):
    import backend.services.scheduler_logic as sl

    # Freeze now to 08:00 IST today so all slots today are future
    fake_now = _ist_at(8)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)

    slot = sl.pick_next_slot("channel_a", db=MagicMock())
    assert (slot.hour, slot.minute) in ((12, 30), (18, 30)), f"Unexpected slot: {slot}"


# ---- 5.0-hour anti-clustering rule --------------------------------------- #

def test_gap_rule(monkeypatch):
    import backend.services.scheduler_logic as sl

    fake_now = _ist_at(8)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)

    # Simulate a video published at 12:30 today — Slot A occupied
    existing_1230 = fake_now.replace(hour=12, minute=30, second=0)
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: [existing_1230])
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])

    slot = sl.pick_next_slot("channel_a", db=MagicMock())

    # 12:30 is taken; 18:30 is 6h later (>5h), should be available
    gap = abs((slot - existing_1230).total_seconds()) / 3600
    assert gap >= 5.0, f"Returned slot {slot} is only {gap:.1f}h from existing — gap rule violated"


def test_gap_blocks_slot_b_when_too_close(monkeypatch):
    import backend.services.scheduler_logic as sl

    fake_now = _ist_at(8)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)

    # 12:30 and 16:30 both occupied — 18:30 is only 2h from 16:30 so blocked
    existing = [
        fake_now.replace(hour=12, minute=30, second=0),
        fake_now.replace(hour=16, minute=30, second=0),
    ]
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: existing)
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])

    slot = sl.pick_next_slot("channel_a", db=MagicMock())
    # Today slots blocked — must return tomorrow slot A (12:30)
    assert (slot.hour, slot.minute) == (12, 30)
    assert slot.date() > fake_now.date()


# ---- Slot-in-past rule ---------------------------------------------------- #

def test_past_slot_skipped(monkeypatch):
    import backend.services.scheduler_logic as sl

    # Freeze now to 14:00 IST — Slot A (12:00) already passed
    fake_now = _ist_at(14)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: [])
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])

    slot = sl.pick_next_slot("channel_a", db=MagicMock())
    # Slot A today is past — next should be Slot B today (18:00) or tomorrow
    assert slot > fake_now


# ---- No slot available → RuntimeError ------------------------------------- #

def test_no_slot_raises(monkeypatch):
    import backend.services.scheduler_logic as sl

    fake_now = _ist_at(8)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)

    # Fill ALL slots for 14 days with 4h gaps (blocks everything)
    occupied = []
    base = fake_now.replace(hour=0, minute=0, second=0)
    for i in range(14 * 6):  # every 4 hours for 14 days
        occupied.append(base + timedelta(hours=i * 4))
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: occupied)
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])

    with pytest.raises(RuntimeError, match="No available slot"):
        sl.pick_next_slot("channel_a", db=MagicMock())


# ---- videoCount < 20 doesn't crash, still returns a valid slot ------------ #

def test_early_growth_channel(monkeypatch):
    import backend.services.scheduler_logic as sl

    fake_now = _ist_at(8)
    monkeypatch.setattr(sl, "_ist_now", lambda: fake_now)
    monkeypatch.setattr(sl, "_get_channel_video_count", lambda ch: 5)
    monkeypatch.setattr(sl, "_get_db_publish_times", lambda ch, db: [])
    monkeypatch.setattr(sl, "_get_recent_publish_times_youtube", lambda ch: [])

    slot = sl.pick_next_slot("channel_a", db=MagicMock())
    assert slot > fake_now
