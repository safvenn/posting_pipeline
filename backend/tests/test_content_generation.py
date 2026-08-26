"""Unit tests for content generation (mocked Gemini)."""
from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import MagicMock, patch

from backend.services.asmr.content_generation import ContentGenerationService, PROMPT_TEMPLATE_PATH
from backend.services.asmr.errors import ContentValidationError


# ---- Prompt template ------------------------------------------------------- #

def test_prompt_template_exists():
    assert PROMPT_TEMPLATE_PATH.exists(), f"Prompt template not found: {PROMPT_TEMPLATE_PATH}"

def test_prompt_template_has_placeholder():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{food_item}" in text, "Prompt template missing {food_item} placeholder"

def test_prompt_template_has_negative_rules():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "NEGATIVE RULES" in text
    assert "no watermark" in text
    assert "no text" in text

def test_prompt_template_has_scale_lock():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "SCALE LOCK" in text

def test_prompt_template_has_environment_lock():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "ENVIRONMENT LOCK" in text

def test_prompt_template_has_asmr_sound_design():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "ASMR SOUND DESIGN" in text

def test_prompt_template_has_all_shots():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    for i in range(1, 10):
        assert f"SHOT {i}" in text, f"Missing SHOT {i}"


# ---- Content generation with mocked Gemini -------------------------------- #

VALID_GEMINI_RESPONSE = json.dumps({
    "caption": "Tiny crispy samosa, handcrafted to perfection 🍳\nPure ASMR bliss in every fold.",
    "description": "Watch this miniature samosa being made from scratch. Subscribe for daily ASMR!",
    "tags": [
        "asmr", "miniature cooking", "tiny food", "samosa", "indian food",
        "satisfying", "cooking asmr", "shorts", "asmr cooking", "relaxing",
        "mini kitchen", "tiny kitchen", "handcrafted", "food asmr", "indian asmr",
    ],
    "prompt": "Ultra-realistic macro cinematic video, 8K, authentic miniature ASMR cooking experience. " * 20,
})


def test_generate_with_valid_gemini_response():
    """Full generation pipeline with valid mock Gemini output."""
    mock_gemini = MagicMock()
    mock_gemini.generate_json.return_value = json.loads(VALID_GEMINI_RESPONSE)

    service = ContentGenerationService(gemini=mock_gemini)
    result = service.generate("samosa")

    assert result.food_item == "samosa"
    assert result.title  # non-empty
    assert len(result.title) <= 60
    assert result.caption
    assert result.description
    assert len(result.tags) >= 10
    assert len(result.hashtags) >= 5
    assert result.video_prompt


def test_generate_retries_on_bad_json():
    """Retries with correction prompt when first response is invalid."""
    mock_gemini = MagicMock()
    # First call returns bad structure
    mock_gemini.generate_json.side_effect = [
        {"wrong_key": "value"},  # missing required fields
        json.loads(VALID_GEMINI_RESPONSE),  # retry succeeds
    ]

    service = ContentGenerationService(gemini=mock_gemini)
    result = service.generate("samosa")
    assert result.food_item == "samosa"
    assert mock_gemini.generate_json.call_count == 2


def test_generate_fails_after_both_attempts():
    """Raises ContentValidationError when both attempts fail."""
    mock_gemini = MagicMock()
    mock_gemini.generate_json.side_effect = [
        {"wrong": "data"},
        {"still_wrong": "data"},
    ]

    service = ContentGenerationService(gemini=mock_gemini)
    with pytest.raises(ContentValidationError):
        service.generate("samosa")


# ---- Title generation ------------------------------------------------------ #

def test_title_from_short_caption():
    """Title uses caption first line when under 60 chars."""
    title = ContentGenerationService._generate_title("samosa", "Mini Samosa Magic")
    assert title == "Mini Samosa Magic"
    assert len(title) <= 60

def test_title_fallback_when_caption_too_long():
    """Falls back to food-item-based title when caption is too long."""
    long_caption = "A" * 100
    title = ContentGenerationService._generate_title("samosa", long_caption)
    assert len(title) <= 60
    assert "samosa" in title.lower() or "Samosa" in title


# ---- Hashtag extraction --------------------------------------------------- #

def test_hashtag_extraction():
    hashtags = ContentGenerationService._extract_hashtags(
        ["asmr", "miniature cooking", "tiny food", "satisfying", "shorts"]
    )
    assert len(hashtags) >= 5
    for h in hashtags:
        assert h.startswith("#")

def test_hashtag_minimum_padding():
    hashtags = ContentGenerationService._extract_hashtags(["single"])
    assert len(hashtags) >= 5
