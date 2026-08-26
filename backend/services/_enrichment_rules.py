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
    "Watch how to make",
    "See why everyone loves this",
    "This is why you'll love",
    "You won't believe this tiny",
    "Here's how to cook",
    "Try this crispy",
    "Best ever miniature",
    "Step-by-step tiny",
]


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(";") if t.strip()]


def _to_hashtag(tag: str) -> str:
    return "#" + re.sub(r"[^a-z0-9]", "", tag.lower().replace(" ", ""))


def enrich_title(original: str, channel: str) -> str:
    original = original.strip()
    # If original already starts with a hook word
    if any(original.lower().startswith(w.lower())
           for w in ("how", "why", "what", "watch", "best", "this", "try", "see", "step", "here", "you")):
        title = original
    else:
        hook = _HOOK_STARTERS[hash(original) % len(_HOOK_STARTERS)]
        title = f"{hook}: {original}"

    if len(title) > 70:
        title = title[:67].rsplit(" ", 1)[0] + "..."
    return title


def enrich_tags(post_tags: str, channel: str) -> str:
    post_tag_list = _parse_tags(post_tags)
    seo_pool = settings.seo_tags_for(channel)
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
    defaults = ["miniature cooking", "tiny food", "asmr cooking", "satisfying video", "shorts", "street food"]
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
        body = "Experience the authentic sizzle, aromas, and sensory joy of miniature cooking crafted with real ingredients in a tiny handcrafted kitchen."
    
    # Layer 2: Subscribe CTA (if under subscriber threshold)
    if subscriber_count < SUBSCRIBER_CTA_THRESHOLD:
        cta = _CTAS.get(channel, "🔔 Subscribe for daily satisfying miniature ASMR cooking adventures!")
        body = f"{body}\n\n{cta}"

    # Layer 3: Engagement comment question
    engagement_prompt = "👉 Would you eat this in one single bite or save it? Rate this miniature dish from 1-10 below! 👇"
    body = f"{body}\n\n{engagement_prompt}"

    # Layer 4: Hashtags
    tag_list = _parse_tags(tags)
    hashtags = [_to_hashtag(t) for t in tag_list[:6] if t]
    default_tags = ["#shorts", "#miniaturecooking", "#tinyfood", "#asmrcooking", "#satisfying", "#indianfood"]
    for dt in default_tags:
        if len(hashtags) >= 8:
            break
        if dt not in hashtags:
            hashtags.append(dt)

    body = body + "\n\n" + " ".join(hashtags)
    return body


def generate_first_comment(channel: str, title: str) -> str:
    template = "Which miniature recipe should we cook next? Top voted comment wins! 👩‍🍳👇"
    words = [w for w in title.split() if len(w) > 3 and w.isalpha()]
    if words:
        topic = words[0].lower()
        if "indian" in channel or channel == "channel_a":
            comment = f"Would you try eating this tiny {topic} in one single bite? Drop your rating 1-10! 😋👇"
        else:
            comment = f"Did the sounds of this miniature {topic} relax you? Tell me below! 💬👇"
    else:
        comment = template
    comment = comment[:199]
    emoji_count = sum(1 for c in comment if ord(c) > 0x1F300)
    if emoji_count == 0:
        comment = comment.rstrip() + " 👇"
    elif emoji_count > 1:
        comment = re.sub(r"[^\x00-\x7F]+", "", comment).strip() + " 👇"
    return comment[:199]


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
