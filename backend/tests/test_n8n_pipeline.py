"""Unit tests for ported n8n workflow components: gwr watermark, Gemini enrichment, and Sheets."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services.enrichment import _build_prompt, _parse_gemini_json
from backend.services.watermark import _check_gwr_json, _parse_gwr_error


# ---- Watermark (gwr) output parsing & error handling ------------------------ #

def test_parse_gwr_error_json():
    json_err = json.dumps({"success": False, "error": "Video codec unsupported: prores"})
    err_msg = _parse_gwr_error(json_err, "")
    assert "Video codec unsupported: prores" in err_msg


def test_parse_gwr_error_stderr_fallback():
    err_msg = _parse_gwr_error("", "Command failed: ffmpeg exited 1")
    assert "ffmpeg exited 1" in err_msg


def test_check_gwr_json_success():
    valid_json = json.dumps({"success": True, "outputPath": "/tmp/clean.mp4"})
    # Should not raise
    _check_gwr_json(valid_json, post_id=1)


def test_check_gwr_json_failure_raises():
    failure_json = json.dumps({"success": False, "error": "Detection model failed"})
    with pytest.raises(RuntimeError, match="gwr reported failure"):
        _check_gwr_json(failure_json, post_id=1)


# ---- Gemini JSON parsing & Prompt formatting -------------------------------- #

def test_parse_gemini_json_clean():
    payload = {
        "id": 12,
        "title": "Watch This Mini Pizza Cook!",
        "description": "Making tiny pizza in a dollhouse kitchen.",
        "tags": ["mini food", "asmr"],
        "firstComment": "Would you eat this? 🍕",
        "date": "2026-08-21T12:00:00+05:30",
    }
    raw = json.dumps(payload)
    parsed = _parse_gemini_json(raw)
    assert parsed["id"] == 12
    assert parsed["date"].endswith("+05:30")


def test_parse_gemini_json_strips_markdown_code_fences():
    payload = {
        "id": 5,
        "title": "Secret ASMR Technique",
        "description": "Relaxing sounds.",
        "tags": ["asmr"],
        "firstComment": "Did this relax you? 😴",
        "date": "2026-08-21T18:00:00+05:30",
    }
    raw = f"```json\n{json.dumps(payload)}\n```"
    parsed = _parse_gemini_json(raw)
    assert parsed["id"] == 5
    assert parsed["title"] == "Secret ASMR Technique"


def test_build_prompt_contains_rules_and_channel_info():
    channel_details = {"snippet": {"title": "The Indian Kitchen"}, "statistics": {"videoCount": "15", "subscriberCount": "450"}}
    recent_videos = [{"id": {"videoId": "abc1234"}, "snippet": {"publishedAt": "2026-08-20T12:00:00Z"}}]
    rows = [{"id": 1, "title": "Mini Dosa", "scheduled": ""}]
    
    prompt = _build_prompt(
        channel="channel_a",
        channel_details=channel_details,
        recent_videos=recent_videos,
        current_ist="2026-08-20T16:00:00+05:30",
        all_rows=rows,
    )
    
    assert "The Indian Kitchen" in prompt
    assert "Mini Dosa" in prompt
    assert "+05:30" in prompt
    assert "5 HOURS" in prompt
    assert "Slot A" in prompt
    assert "Slot B" in prompt


# ---- Google Sheets helper tests (mocked) ------------------------------------ #

def test_get_first_unscheduled_row(monkeypatch):
    from backend.services import sheets
    
    mock_rows = [
        {"id": 1, "title": "Video 1", "scheduled": "2026-08-19T12:00:00+05:30"},
        {"id": 2, "title": "Video 2", "scheduled": ""},
        {"id": 3, "title": "Video 3", "scheduled": ""},
    ]
    monkeypatch.setattr(sheets, "get_all_rows", lambda ch: mock_rows)
    
    row = sheets.get_first_unscheduled_row("channel_a")
    assert row is not None
    assert row["id"] == 2
    assert row["title"] == "Video 2"


def test_get_first_unscheduled_row_none_when_all_scheduled(monkeypatch):
    from backend.services import sheets
    
    mock_rows = [
        {"id": 1, "title": "Video 1", "scheduled": "2026-08-19T12:00:00+05:30"},
        {"id": 2, "title": "Video 2", "scheduled": "2026-08-20T18:00:00+05:30"},
    ]
    monkeypatch.setattr(sheets, "get_all_rows", lambda ch: mock_rows)
    
    row = sheets.get_first_unscheduled_row("channel_a")
    assert row is None
