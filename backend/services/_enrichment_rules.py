"""
Rule-based content enrichment fallback (used when GEMINI_API_KEY is not set).
Original implementation — kept as _enrichment_rules.py so the Gemini module can import it.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

SUBSCRIBER_CTA_THRESHOLD = 1000

_CTAS = {
    "channel_a": "🔔 Subscribe for more amazing recipes every week!",
    "channel_b": "🔔 Subscribe for daily satisfying ASMR content!",
}

_COMMENT_TEMPLATES = {
    "channel_a": "What dish should I try next? Drop your suggestion below! 👇",
    "channel_b": "Which sound was your favourite in this video? Let me know! 💬",
}

_HOOK_STARTERS = [
    "Watch this amazing",
    "See why everyone loves this",
    "This is why you'll love",
    "You won't believe this",
    "Check out this incredible",
    "Experience this stunning",
    "Take a look at",
    "Best ever",
]

_COOKING_HOOK_STARTERS = [
    "Watch how to make",
    "See why everyone loves this",
    "This is why you'll love",
    "You won't believe this tiny",
    "Here's how to cook",
    "Try this crispy",
    "Best ever miniature",
    "Step-by-step tiny",
]


def _is_cooking_channel(channel: str, text: str = "") -> bool:
    ch = (channel or "").lower()
    tx = (text or "").lower()
    if any(k in ch for k in ("kitchen", "cook", "food", "dish", "recipe", "channel_a")):
        return True
    if any(k in tx for k in ("cook", "kitchen", "recipe", "dish", "biryani", "curry", "baking", "food")):
        return True
    return False


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(";") if t.strip()]


def _to_hashtag(tag: str) -> str:
    return "#" + re.sub(r"[^a-z0-9]", "", tag.lower().replace(" ", ""))


def enrich_title(original: str, channel: str) -> str:
    original = original.strip()
    # If original already starts with a hook word
    if any(original.lower().startswith(w.lower())
           for w in ("how", "why", "what", "watch", "best", "this", "try", "see", "step", "here", "you", "check", "experience")):
        title = original
    else:
        # Channel names cannot establish the content of this particular video.
        starters = _HOOK_STARTERS
        hook = starters[hash(original) % len(starters)]
        title = f"{hook}: {original}"

    if len(title) > 70:
        title = title[:67].rsplit(" ", 1)[0] + "..."
    return title


def enrich_tags(post_tags: str, channel: str) -> str:
    post_tag_list = _parse_tags(post_tags)
    # The legacy settings helper returns channel B's tags for every other key.
    # Custom channels must never inherit another channel's SEO configuration.
    seo_pool = settings.seo_tags_for(channel) if channel in ("channel_a", "channel_b") else []
    seen: set[str] = {t.lower() for t in post_tag_list}
    merged = list(post_tag_list)
    added = 0
    for seo_tag in seo_pool:
        if added >= 8:
            break
        if seo_tag.lower() not in seen:
            merged.append(seo_tag)
            seen.add(seo_tag.lower())
            added += 1
    # Ensure standard discovery tags
    defaults = ["shorts"]
    for d in defaults:
        if len(merged) >= 20:
            break
        if d.lower() not in seen:
            merged.append(d)
            seen.add(d.lower())
    return ";".join(merged[:20])


def enrich_description(original: str, channel: str, subscriber_count: int, tags: str) -> str:
    body = original.strip()
    if not body:
        body = "Watch this short video and share your thoughts."
    
    # Layer 2: Subscribe CTA (if under subscriber threshold)
    if subscriber_count < SUBSCRIBER_CTA_THRESHOLD:
        cta = "🔔 Subscribe for more videos!"
        body = f"{body}\n\n{cta}"

    # Layer 3: Engagement comment question
    engagement_prompt = "👉 What did you think of this? Share your thoughts below!"
    body = f"{body}\n\n{engagement_prompt}"

    # Layer 4: Hashtags
    tag_list = _parse_tags(tags)
    hashtags = [_to_hashtag(t) for t in tag_list[:6] if t]
    default_tags = ["#shorts"]
    for dt in default_tags:
        if len(hashtags) >= 8:
            break
        if dt not in hashtags:
            hashtags.append(dt)

    body = body + "\n\n" + " ".join(hashtags)
    return body


def generate_first_comment(channel: str, title: str) -> str:
    return "What stood out to you in this video? Share your thoughts below! 👇"


def enrich_post(channel: str, title: str, description: str,
                tags: str, subscriber_count: int = 0) -> dict:
    enriched_title = enrich_title(title, channel)
    enriched_tags = enrich_tags(tags, channel)
    enriched_description = enrich_description(description, channel, subscriber_count, enriched_tags)
    first_comment = generate_first_comment(channel, enriched_title)
    return {
        "enriched_title": enriched_title,
        "enriched_description": enriched_description,
        "enriched_tags": enriched_tags,
        "first_comment_text": first_comment,
    }
