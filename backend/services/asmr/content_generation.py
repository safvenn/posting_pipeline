"""
ASMR content generation via Gemini.

Pipeline:
  1. Load versioned prompt template
  2. Inject food item
  3. Call GeminiService with SEO system instruction
  4. Parse into Pydantic ContentGenerationResult
  5. Build full ASMRContentResult with title, hashtags
  6. Validate via SEOService
  7. Retry once on parse/validation failure
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend.schemas import ASMRContentResult, ContentGenerationResult
from backend.services.asmr.errors import ContentValidationError, GeminiAPIError
from backend.services.asmr.seo_service import SEOService
from backend.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "asmr_miniature_v1.md"

# System instruction for the SEO/content generation agent
# Verbatim from n8n "Prompt generation agent and seo" system message
SEO_SYSTEM_INSTRUCTION = (
    "You write YouTube Shorts / Instagram Reels metadata for miniature ASMR "
    "Indian food videos. Output: 1) a scroll-stopping title under 60 characters, "
    "2) a caption (2-3 lines, sensory/curiosity-driven, 1 relevant emoji max), "
    "3) a description (2-3 sentences + a soft CTA to follow/subscribe), "
    "4) 15-20 tags mixing niche (miniature cooking, tiny food, mini ASMR) and "
    "broad (asmr, satisfying, cooking) reach terms, and 5) 5-8 hashtags for "
    "the caption itself. Never use clickbait that misrepresents the video.\n"
    "must exact length of the example prompt\n\n"
    "use json format only must follow this strictly: caption, description, tags, prompt"
)


class ContentGenerationService:
    """Generates ASMR content (title, caption, description, tags, hashtags, video prompt)."""

    def __init__(self, gemini: GeminiService | None = None):
        self._gemini = gemini or GeminiService()
        self._seo = SEOService()
        self._prompt_template = self._load_prompt_template()

    @staticmethod
    def _load_prompt_template() -> str:
        """Load the versioned ASMR prompt template."""
        if not PROMPT_TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"ASMR prompt template not found: {PROMPT_TEMPLATE_PATH}")
        return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    def generate(self, food_item: str) -> ASMRContentResult:
        """
        Generate full ASMR content for a food item.
        Retries once on parse/validation failure with correction prompt.
        """
        # Build prompt: template with food item + request for JSON output
        video_prompt = self._prompt_template.replace("{food_item}", food_item)

        user_prompt = (
            f"{food_item}\n\n"
            "Generate the following as valid JSON only (no markdown, no code fences):\n"
            "{\n"
            '  "caption": "...",\n'
            '  "description": "...",\n'
            '  "tags": ["tag1", "tag2", ...],\n'
            '  "prompt": "full video generation prompt"\n'
            "}\n\n"
            f"The video prompt should be based on this master template:\n\n{video_prompt}"
        )

        # First attempt
        last_error: Exception | None = None
        try:
            result = self._call_and_parse(user_prompt, food_item)
            return result
        except (ContentValidationError, GeminiAPIError) as first_error:
            last_error = first_error
            logger.warning("First generation attempt failed: %s. Retrying with correction.", first_error)

        # Retry with correction prompt
        correction_prompt = (
            f"Your previous response had an error: {last_error}\n\n"
            "Please fix and return valid JSON only with these exact keys:\n"
            "caption, description, tags (array), prompt\n\n"
            f"Subject: {food_item}"
        )
        try:
            return self._call_and_parse(correction_prompt, food_item)
        except (ContentValidationError, GeminiAPIError) as second_error:
            raise ContentValidationError(
                "generation",
                f"Failed after retry: {second_error}",
            ) from second_error

    def _call_and_parse(self, prompt: str, food_item: str) -> ASMRContentResult:
        """Call Gemini, parse JSON, build and validate ASMRContentResult."""
        raw_dict = self._gemini.generate_json(prompt, SEO_SYSTEM_INSTRUCTION)

        # Parse into ContentGenerationResult (n8n's output format)
        try:
            gen_result = ContentGenerationResult(**raw_dict)
        except Exception as exc:
            raise ContentValidationError(
                "json_structure",
                f"Response missing required fields: {exc}. Got keys: {list(raw_dict.keys())}",
            ) from exc

        # Build full content result
        title = self._generate_title(food_item, gen_result.caption)
        hashtags = self._extract_hashtags(gen_result.tags)

        content = ASMRContentResult(
            food_item=food_item,
            title=title,
            caption=gen_result.caption,
            description=gen_result.description,
            tags=gen_result.tags,
            hashtags=hashtags,
            video_prompt=gen_result.prompt,
        )

        # Validate via SEO service
        content = self._seo.validate_and_fix(content)
        return content

    @staticmethod
    def _generate_title(food_item: str, caption: str) -> str:
        """Generate a scroll-stopping title under 60 chars."""
        # Use first line of caption if short enough, else build from food item
        first_line = caption.split("\n")[0].strip()
        if len(first_line) <= 60:
            return first_line

        # Build title from food item name
        title = f"Miniature {food_item.title()} ASMR 🍳"
        if len(title) > 60:
            title = f"Mini {food_item.title()} ASMR"
        return title[:60]

    @staticmethod
    def _extract_hashtags(tags: list[str]) -> list[str]:
        """Extract/generate 5-8 hashtags from tags list."""
        hashtags = []
        for tag in tags[:8]:
            # Clean and convert to hashtag format
            cleaned = tag.strip().lower().replace(" ", "")
            if cleaned:
                if not cleaned.startswith("#"):
                    cleaned = f"#{cleaned}"
                hashtags.append(cleaned)
        # Ensure minimum 5
        defaults = ["#asmr", "#miniaturecooking", "#tinyfood", "#satisfying", "#shorts"]
        for d in defaults:
            if len(hashtags) >= 5:
                break
            if d not in hashtags:
                hashtags.append(d)
        return hashtags[:8]
