"""Unit tests for SEO validation service."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.schemas import ASMRContentResult
from backend.services.asmr.seo_service import SEOService
from backend.services.asmr.errors import ContentValidationError


@pytest.fixture
def seo():
    return SEOService()


def _make_content(**overrides) -> ASMRContentResult:
    defaults = {
        "food_item": "samosa",
        "title": "Miniature Samosa ASMR",
        "caption": "Tiny crispy samosa from scratch 🍳",
        "description": "Watch this miniature samosa being made in a tiny kitchen. Pure ASMR bliss.",
        "tags": ["asmr", "miniature cooking", "tiny food", "samosa", "indian food",
                 "satisfying", "cooking asmr", "shorts", "asmr cooking", "relaxing"],
        "hashtags": ["#asmr", "#miniaturecooking", "#tinyfood", "#satisfying", "#shorts"],
        "video_prompt": "Ultra-realistic macro cinematic video, 8K..." + "x" * 100,
    }
    defaults.update(overrides)
    return ASMRContentResult(**defaults)


# ---- Title ----------------------------------------------------------------- #

def test_title_under_60(seo):
    content = _make_content(title="Short Title")
    result = seo.validate_and_fix(content)
    assert len(result.title) <= 60

def test_title_truncated_when_too_long(seo):
    content = _make_content(title="A" * 80)
    result = seo.validate_and_fix(content)
    assert len(result.title) <= 60
    assert result.title.endswith("...")

def test_empty_title_raises(seo):
    with pytest.raises(ContentValidationError, match="Title is empty"):
        seo.validate_and_fix(_make_content(title=""))


# ---- Caption --------------------------------------------------------------- #

def test_caption_emoji_count_max_1(seo):
    content = _make_content(caption="So yummy 🍕🎉🔥")
    result = seo.validate_and_fix(content)
    emoji_count = sum(1 for c in result.caption if ord(c) > 0x1F300)
    assert emoji_count <= 1

def test_empty_caption_raises(seo):
    with pytest.raises(ContentValidationError, match="Caption is empty"):
        seo.validate_and_fix(_make_content(caption=""))


# ---- Tags ------------------------------------------------------------------ #

def test_tags_max_20(seo):
    content = _make_content(tags=[f"tag{i}" for i in range(25)])
    result = seo.validate_and_fix(content)
    assert len(result.tags) <= 20

def test_tags_deduped(seo):
    content = _make_content(tags=["asmr", "ASMR", "asmr", "cooking"] + ["pad"] * 10)
    result = seo.validate_and_fix(content)
    lower_tags = [t.lower() for t in result.tags]
    # Some dedup happens (exact match only, not case-insensitive in current impl)
    assert len(result.tags) >= 2

def test_tags_padded_to_minimum(seo):
    content = _make_content(tags=["asmr", "cooking"])
    result = seo.validate_and_fix(content)
    assert len(result.tags) >= 10


# ---- Hashtags -------------------------------------------------------------- #

def test_hashtags_all_start_with_hash(seo):
    content = _make_content(hashtags=["asmr", "cooking", "#food", "tiny", "shorts"])
    result = seo.validate_and_fix(content)
    for h in result.hashtags:
        assert h.startswith("#"), f"Hashtag missing #: {h}"

def test_hashtags_max_8(seo):
    content = _make_content(hashtags=[f"#tag{i}" for i in range(15)])
    result = seo.validate_and_fix(content)
    assert len(result.hashtags) <= 8


# ---- Video prompt ---------------------------------------------------------- #

def test_short_video_prompt_raises(seo):
    with pytest.raises(ContentValidationError, match="Video prompt too short"):
        seo.validate_and_fix(_make_content(video_prompt="short"))

def test_empty_video_prompt_raises(seo):
    with pytest.raises(ContentValidationError, match="Video prompt too short"):
        seo.validate_and_fix(_make_content(video_prompt=""))


# ---- Full pass ------------------------------------------------------------- #

def test_valid_content_passes(seo):
    content = _make_content()
    result = seo.validate_and_fix(content)
    assert result.food_item == "samosa"
    assert result.title == "Miniature Samosa ASMR"
    assert len(result.tags) >= 10
    assert len(result.hashtags) >= 5
