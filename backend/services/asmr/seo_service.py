"""
SEO validation service for ASMR content.

AI generates content. Application code validates content.
This separation is mandatory.
"""
from __future__ import annotations

import logging
import re

from backend.schemas import ASMRContentResult
from backend.services.asmr.errors import ContentValidationError

logger = logging.getLogger(__name__)

# Platform constraints
MAX_TITLE_LENGTH = 60
MAX_CAPTION_LINES = 4
MIN_TAGS = 10
MAX_TAGS = 20
MIN_HASHTAGS = 5
MAX_HASHTAGS = 8
MAX_DESCRIPTION_LENGTH = 5000


class SEOService:
    """Validates and fixes SEO metadata for ASMR content."""

    def validate_and_fix(self, content: ASMRContentResult) -> ASMRContentResult:
        """
        Validate content against platform constraints.
        Fixes where possible, raises ContentValidationError if unfixable.
        """
        # Title
        title = content.title.strip()
        if not title:
            raise ContentValidationError("title", "Title is empty")
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH - 3].rsplit(" ", 1)[0] + "..."
            logger.debug("Title truncated to %d chars", len(title))

        # Caption
        caption = content.caption.strip()
        if not caption:
            raise ContentValidationError("caption", "Caption is empty")
        caption_lines = [l for l in caption.split("\n") if l.strip()]
        if len(caption_lines) > MAX_CAPTION_LINES:
            caption = "\n".join(caption_lines[:MAX_CAPTION_LINES])
            logger.debug("Caption truncated to %d lines", MAX_CAPTION_LINES)

        # Emoji count in caption — max 1
        emoji_count = sum(1 for c in caption if ord(c) > 0x1F300)
        if emoji_count > 1:
            # Remove extra emojis, keep first
            found = 0
            cleaned = []
            for c in caption:
                if ord(c) > 0x1F300:
                    found += 1
                    if found > 1:
                        continue
                cleaned.append(c)
            caption = "".join(cleaned)

        # Description
        description = content.description.strip()
        if not description:
            raise ContentValidationError("description", "Description is empty")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH]

        # Tags
        tags = [t.strip() for t in content.tags if t.strip()]
        tags = list(dict.fromkeys(tags))  # dedup preserving order
        if len(tags) < MIN_TAGS:
            # Pad with defaults
            defaults = [
                "asmr", "miniature cooking", "tiny food", "satisfying",
                "cooking asmr", "indian food", "mini kitchen", "shorts",
                "asmr cooking", "relaxing",
            ]
            for d in defaults:
                if d not in tags:
                    tags.append(d)
                if len(tags) >= MIN_TAGS:
                    break
        tags = tags[:MAX_TAGS]

        # Hashtags
        hashtags = content.hashtags
        # Ensure all start with #
        hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags]
        # Remove non-alphanumeric (except #)
        hashtags = [re.sub(r"[^#a-zA-Z0-9]", "", h) for h in hashtags]
        hashtags = [h for h in hashtags if len(h) > 1]
        hashtags = list(dict.fromkeys(hashtags))[:MAX_HASHTAGS]

        if len(hashtags) < MIN_HASHTAGS:
            defaults = ["#asmr", "#miniaturecooking", "#tinyfood", "#satisfying", "#shorts",
                         "#indianfood", "#cookingasmr", "#relaxing"]
            for d in defaults:
                if d not in hashtags:
                    hashtags.append(d)
                if len(hashtags) >= MIN_HASHTAGS:
                    break

        # Video prompt
        video_prompt = content.video_prompt.strip()
        if not video_prompt or len(video_prompt) < 100:
            raise ContentValidationError("video_prompt", "Video prompt too short or empty")

        return ASMRContentResult(
            food_item=content.food_item,
            title=title,
            caption=caption,
            description=description,
            tags=tags,
            hashtags=hashtags,
            video_prompt=video_prompt,
        )
