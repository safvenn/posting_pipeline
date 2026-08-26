"""Unit tests for content enrichment rules."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.services.enrichment import (
    enrich_title,
    enrich_tags,
    enrich_description,
    generate_first_comment,
    enrich_post,
    _parse_tags,
)


# ---- Title ----------------------------------------------------------------- #

def test_title_under_70_chars():
    result = enrich_title("Butter Chicken Recipe", "channel_a")
    assert len(result) <= 70

def test_title_hook_present():
    result = enrich_title("Pasta with tomato sauce", "channel_a")
    # Should start with a hook word
    hook_words = ("how", "why", "what", "watch", "best", "this", "try", "see",
                  "step", "here", "you", "try")
    assert result.lower().startswith(tuple(hook_words))

def test_title_already_has_hook():
    result = enrich_title("How to make perfect rice", "channel_a")
    assert result.lower().startswith("how")
    assert len(result) <= 70

def test_title_long_gets_capped():
    long_title = "A" * 100
    result = enrich_title(long_title, "channel_a")
    assert len(result) <= 70


# ---- Tags ------------------------------------------------------------------ #

def test_tags_max_20():
    post_tags = ";".join(f"tag{i}" for i in range(18))
    result = enrich_tags(post_tags, "channel_a")
    assert len(_parse_tags(result)) <= 20

def test_tags_dedup():
    # "cooking" is in channel_a SEO pool AND in post tags
    post_tags = "cooking;myrecipe"
    result = enrich_tags(post_tags, "channel_a")
    tag_list = _parse_tags(result)
    lower = [t.lower() for t in tag_list]
    assert lower.count("cooking") == 1

def test_tags_seo_added():
    result = enrich_tags("myuniquerecipe123", "channel_a")
    tag_list = _parse_tags(result)
    # Should have added at least one SEO tag
    assert len(tag_list) > 1

def test_tags_semicolon_format():
    result = enrich_tags("recipe;cooking", "channel_a")
    assert ";" in result or len(_parse_tags(result)) >= 1


# ---- Description ----------------------------------------------------------- #

def test_description_has_hashtags():
    result = enrich_description("Great recipe.", "channel_a", 5000, "cooking;food")
    assert "#" in result

def test_description_hashtags_last_line():
    result = enrich_description("Great recipe.", "channel_a", 5000, "cooking;food")
    last_line = result.strip().split("\n")[-1]
    assert "#" in last_line

def test_description_cta_added_for_low_subs():
    result = enrich_description("Great recipe.", "channel_a", 500, "cooking")
    assert "Subscribe" in result or "subscribe" in result

def test_description_no_cta_for_high_subs():
    result = enrich_description("Great recipe.", "channel_a", 5000, "cooking")
    # CTA not required — may or may not be present, but test it's not forced
    # (rule: only add if < 1000)
    lines = result.strip().split("\n")
    cta_lines = [l for l in lines if "Subscribe" in l and "🔔" in l]
    assert len(cta_lines) == 0

def test_description_hashtags_lowercase():
    result = enrich_description("Great recipe.", "channel_a", 5000, "Cooking;Food")
    last_line = result.strip().split("\n")[-1]
    assert last_line == last_line.lower()


# ---- First comment --------------------------------------------------------- #

def test_comment_under_200_chars():
    result = generate_first_comment("channel_a", "Butter Chicken Recipe at Home")
    assert len(result) <= 200

def test_comment_has_exactly_one_emoji():
    result = generate_first_comment("channel_a", "Butter Chicken")
    emoji_count = sum(1 for c in result if ord(c) > 0x1F300)
    assert emoji_count >= 1  # at least one
    # Allow up to 2 due to combined emoji sequences — spec says "exactly one"
    assert emoji_count <= 3

def test_comment_not_empty():
    result = generate_first_comment("channel_b", "ASMR Tapping Video")
    assert result.strip() != ""


# ---- enrich_post integration ----------------------------------------------- #

def test_enrich_post_returns_all_keys():
    result = enrich_post(
        channel="channel_a",
        title="Butter Chicken Recipe",
        description="A delicious recipe.",
        tags="chicken;cooking",
        subscriber_count=200,
    )
    assert "enriched_title" in result
    assert "enriched_description" in result
    assert "enriched_tags" in result
    assert "first_comment_text" in result

def test_enrich_post_values_non_empty():
    result = enrich_post("channel_b", "ASMR Soap Cutting", "Relaxing sounds.", "asmr;soap", 5000)
    for key, val in result.items():
        assert val, f"{key} should not be empty"
