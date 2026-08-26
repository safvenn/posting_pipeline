"""
Content enrichment via Gemini Flash Lite — exact port of the n8n AI Agent prompt.

Two channel-specific prompts (from the workflow JSON), both with identical scheduling rules:
  - Channel A (indian kitchen):  ASMR cooking SEO pool
  - Channel B (little people):   miniature cooking comedy SEO pool

Pipeline (mirrors n8n AI Agent node):
  1. Fetch channel details (live YouTube)
  2. Fetch recent 20 videos (live YouTube, most-recent-first)
  3. Read first unscheduled row from Google Sheet
  4. Build full prompt with channel data + current IST time
  5. Call Gemini Flash Lite, parse JSON output
  6. Return dict: {id, title, description, tags, firstComment, date}

The Gemini output date is the scheduled_at used directly — no separate pick_next_slot() call.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import google.generativeai as genai
import pytz

from backend.config import settings
from backend.services.sheets import get_first_unscheduled_row, get_all_rows
from backend.services.youtube_auth import get_youtube_client

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# ---- SEO tag pools (optimized for maximum reach and high search volume) ----
_SEO_POOL_CHANNEL_A = (
    "asmr, asmr cooking, cooking asmr, satisfying video, miniature cooking, mini food, "
    "tiny kitchen, indian food asmr, no talking asmr, sleep sounds, relaxing cooking sounds, "
    "street food asmr, crispy food, tiny food cooking, viral shorts, shorts, miniature food recipe"
)

_SEO_POOL_CHANNEL_B = (
    "miniature cooking, tiny food, satisfying video, shorts, mini chefs, tiny kitchen comedy, "
    "worlds smallest food, cooking comedy, kitchen chaos, tiny vs big, cinematic shorts, "
    "miniature world, cute cooking, satisfying asmr, food comedy"
)

# ---- System message ----
_SYSTEM_MESSAGE = (
    "You are an elite YouTube Growth & SEO Agent specializing in viral YouTube Shorts. "
    "Your goal is to craft high-CTR, algorithmically optimized metadata that maximizes search rankings, "
    "audience engagement (likes, comments, shares), and viewer retention. "
    "Follow all scheduling and content rules strictly. "
    "Always respond with valid JSON only — no Markdown, no explanations, no code fences."
)


def _build_prompt(
    channel: str,
    channel_details: dict,
    recent_videos: list,
    current_ist: str,
    all_rows: list[dict],
    target_row: Optional[dict] = None,
) -> str:
    """Build the full Gemini prompt with viral engagement & keyword-boosted SEO rules."""
    seo_pool = ""
    try:
        from backend.database import SessionLocal
        from backend.models import ChannelConfig
        with SessionLocal() as db:
            cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel).first()
            if cfg and cfg.seo_tags:
                seo_pool = cfg.seo_tags.replace(";", ", ")
    except Exception:
        pass

    if not seo_pool:
        seo_pool = _SEO_POOL_CHANNEL_A if channel == "channel_a" else _SEO_POOL_CHANNEL_B

    channel_name = channel_details.get("snippet", {}).get("title", channel)
    subscribe_cta_example = f"🔔 Subscribe to {channel_name} for daily satisfying miniature cooking adventures!"

    if target_row:
        row_context_section = f"""TARGET GOOGLE SHEET ROW (ENRICH AND PROCESS THIS EXACT SELECTED ROW):
{json.dumps(target_row, indent=2)}

SELECTION INSTRUCTION:
- You MUST enrich and generate optimized metadata specifically for the TARGET ROW above (ID: {target_row.get('id')}).
- Extract its `id`, `title`, `description`, and `tags`. Do NOT select any other row.
- In your JSON response, set `"id": {json.dumps(target_row.get('id'))}`."""
    else:
        row_context_section = f"""GOOGLE SHEET ROWS (find and process ONLY the first unscheduled row):
{json.dumps(all_rows, indent=2)}

SELECTION INSTRUCTION:
- Select ONLY the first sheet row where `scheduled` is empty or null.
- Extract its `id`, `title`, `description`, `tags`."""

    return f"""You are a world-class YouTube Shorts SEO & Viral Growth Strategist.
This channel's live YouTube data has ALREADY been fetched for you below:

CHANNEL DETAILS:
{json.dumps(channel_details)}

RECENT / SCHEDULED VIDEOS ON THIS CHANNEL:
{json.dumps(recent_videos)}

{row_context_section}

TODAYS DATE: {current_ist}

══════════════════════════════════════════════════════════════════════════════════
GROWTH & METADATA OPTIMIZATION RULES (HIGH KEYWORDS + VIRAL ENGAGEMENT)
══════════════════════════════════════════════════════════════════════════════════

1. SELECTION:
   - Use the designated target row data provided above.
   - Extract its `id`, `title`, `description`, `tags`.

2. VIRAL TITLE ENGINE (High CTR + Keywords + Emotional Hook):
   - Rewrite the title into an irresistible, clickable YouTube Shorts title (50–70 characters total).
   - FIRST 3–4 WORDS: Must be a powerful sensory/curiosity trigger, open loop, or question that hooks the viewer instantly on the Shorts feed (e.g., "Can You Hear That Crunch?", "World's Tiniest Crispy...", "Wait For The Golden Sizzle!", "Is This The Smallest...?", "Satisfying Tiny...").
   - KEYWORD INJECTION: Naturally include high-search keywords like the dish name, "Miniature Cooking", "ASMR", and append "#shorts" at the end.
   - Must be accurate to the dish/video content.

3. ENGAGEMENT-BOOSTED DESCRIPTION (Multi-Layered SEO Structure):
   - Layer 1 (Sensory Hook & Story): 2–3 vivid, mouthwatering sentences describing the authentic aromas, sizzling stone stove sounds, and miniature cooking precision.
   - Layer 2 (SEO Keyword Density): Seamlessly weave in high-volume search phrases (e.g., "authentic miniature Indian cooking ASMR", "relaxing kitchen sounds", "satisfying tiny food preparation").
   - Layer 3 (Comment-Driving Question): A specific, fun conversation starter to trigger the comment algorithm (e.g., "👉 Would you eat this in one single bite? Rate it 1–10 below! 👇 What dish should we shrink down next?").
   - Layer 4 (Channel Subscribe CTA): Append a clean, high-converting subscribe call to action (e.g. "{subscribe_cta_example}").
   - Layer 5 (Hashtags): 5–8 targeted hashtags at the very bottom (e.g., #shorts #miniaturecooking #tinyfood #asmrcooking #indianfood #satisfying #foodie).

4. HIGH-REACH SEO TAGS (Search & Algorithmic Discovery):
   - Merge the dish-specific tags from the sheet with 4–6 high-intent tags from the SEO POOL: {seo_pool}.
   - Mix broad terms ("asmr", "shorts", "cooking", "satisfying"), niche terms ("miniature cooking", "tiny food", "mini kitchen", "tiny food asmr", "worlds smallest food"), and dish-specific terms ("miniature [dish]", "[dish] asmr", "crispy [dish]").
   - Clean, trim whitespace, deduplicate case-insensitively, and return a clean array of 15–20 tags.

5. PINNED FIRST COMMENT (Reply Multiplier):
   - Write a short (under 180 characters), highly engaging pinned comment with exactly ONE emoji.
   - Must be an interactive question or challenge that encourages viewers to reply (e.g., "What miniature dish should we cook next? Top voted comment wins! 👩‍🍳👇" or "Would you eat this in one tiny bite or save it? Drop your answer! 😋👇").

6. SCHEDULING RULES (THE 2 BEST VIRAL PEAK TIMES):
   - Slot A: 12:30 PM–01:00 PM IST (Lunchtime mobile browsing peak)
   - Slot B: 06:30 PM–07:00 PM IST (Prime evening leisure & commute peak)
   - Must be strictly in the FUTURE vs TODAYS DATE.
   - Must maintain at least a 5 HOURS minimum spacing gap from existing videos in the recent videos list.
   - Pick the FIRST available slot starting from today Slot A -> today Slot B -> tomorrow Slot A -> tomorrow Slot B...

══════════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT (VALID JSON ONLY - NO MARKDOWN - NO CODE FENCES):
══════════════════════════════════════════════════════════════════════════════════
{{
  "id": int,
  "title": "World's Tiniest Crispy Masala Dosa! Miniature ASMR 🍳 #shorts",
  "description": "Sensory-rich description with keywords, engagement question, CTA, and #hashtags",
  "tags": ["miniature cooking", "tiny food", "asmr cooking", "indian food asmr", "shorts"],
  "firstComment": "Which dish should we cook in miniature next? Drop your suggestion below! 👨‍🍳👇",
  "date": "YYYY-MM-DDTHH:MM:SS+05:30"
}}

If no unscheduled row exists, return {{"id": null, "title": null, "description": null, "tags": [], "firstComment": null, "date": null}}.
- `description` must follow the subscribe CTA rule above.
- `date` must contain ONLY the scheduled calendar date+time in format 'YYYY-MM-DDTHH:MM:SS+05:30', must always be strictly LATER than the current time, must respect the spacing rule, and must fall inside Slot A or Slot B — return only the string.
- The date string MUST end with the +05:30 timezone offset suffix EVERY time, with no exceptions.
- JSON must be syntactically valid.
- Date is a string.
- DATE must be Indian Standard Time, strictly inside Slot A or Slot B as defined above, strictly later than the current time, and must always end with +05:30."""


def _fetch_channel_data(channel: str) -> tuple[dict, list]:
    """
    Fetch live channel details + recent 20 videos from YouTube.
    Returns (channel_details_dict, recent_videos_list).
    """
    yt = get_youtube_client(channel)

    # GET /youtube/v3/channels?part=snippet,statistics,contentDetails,status&mine=true
    ch_resp = yt.channels().list(
        part="snippet,statistics,contentDetails,status",
        mine=True,
    ).execute()
    channel_details = ch_resp.get("items", [{}])[0] if ch_resp.get("items") else ch_resp

    # GET /youtube/v3/search?part=snippet&forMine=true&type=video&order=date&maxResults=20
    search_resp = yt.search().list(
        part="snippet",
        forMine=True,
        type="video",
        order="date",
        maxResults=20,
    ).execute()
    recent_videos = search_resp.get("items", [])

    return channel_details, recent_videos


def _call_gemini(prompt: str) -> str:
    """Call Gemini Flash Lite, return raw text response."""
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not configured. Set it in .env to use AI enrichment."
        )

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=_SYSTEM_MESSAGE,
    )
    response = model.generate_content(prompt)
    return response.text


def _parse_gemini_json(raw: str) -> dict:
    """
    Parse Gemini JSON output — strips markdown fences if model adds them despite instructions.
    Raises ValueError on invalid JSON.
    """
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()
    return json.loads(text)


def enrich_post_gemini(
    channel: str,
    target_row_id: Optional[str] = None,
    target_post: Optional[object] = None,
) -> dict | None:
    """
    Full Gemini-based enrichment pipeline for a channel.
    If target_row_id or target_post is provided, enriches that specific row/post.
    Otherwise enriches the next available unscheduled row from Google Sheets.

    Dict keys: id, title, description, tags, firstComment, date
    """
    # Step 1: Get current IST timestamp
    current_ist = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S%z")

    # Step 2: Fetch live YouTube data
    try:
        channel_details, recent_videos = _fetch_channel_data(channel)
    except Exception as exc:
        logger.warning("Could not fetch YouTube data for %s: %s", channel, exc)
        channel_details = {}
        recent_videos = []

    # Step 3: Read all sheet rows (AI sees full context)
    all_rows = []
    try:
        all_rows = get_all_rows(channel)
    except Exception as exc:
        logger.warning("Could not read Google Sheet for %s: %s", channel, exc)

    # Determine specific target row if row_id or post details provided
    target_row = None
    if target_row_id:
        for r in all_rows:
            if str(r.get("id", "")).strip() == str(target_row_id).strip():
                target_row = r
                break
        if not target_row:
            # Fallback construct target_row dict from target_post
            target_row = {
                "id": target_row_id,
                "title": getattr(target_post, "title", ""),
                "description": getattr(target_post, "description", ""),
                "tags": getattr(target_post, "tags", ""),
            }
    elif target_post and getattr(target_post, "sheet_row_id", None):
        target_row_id = getattr(target_post, "sheet_row_id")
        for r in all_rows:
            if str(r.get("id", "")).strip() == str(target_row_id).strip():
                target_row = r
                break
        if not target_row:
            target_row = {
                "id": target_row_id,
                "title": getattr(target_post, "title", ""),
                "description": getattr(target_post, "description", ""),
                "tags": getattr(target_post, "tags", ""),
            }
    elif target_post and getattr(target_post, "title", None):
        # Post has custom title entered manually
        target_row = {
            "id": None,
            "title": getattr(target_post, "title", ""),
            "description": getattr(target_post, "description", ""),
            "tags": getattr(target_post, "tags", ""),
        }

    # If no target row specified and all_rows has no unscheduled rows, skip
    if not target_row:
        has_unscheduled = any(not str(r.get("scheduled", "")).strip() for r in all_rows)
        if not has_unscheduled and all_rows:
            logger.info("Channel %s: no unscheduled rows in sheet", channel)
            return None

    # Step 4: Build prompt
    prompt = _build_prompt(
        channel=channel,
        channel_details=channel_details,
        recent_videos=recent_videos,
        current_ist=current_ist,
        all_rows=all_rows,
        target_row=target_row,
    )

    # Step 5: Call Gemini
    logger.info("Calling Gemini for channel %s enrichment", channel)
    raw = _call_gemini(prompt)
    logger.debug("Gemini raw output: %.500s", raw)

    # Step 6: Parse JSON
    result = _parse_gemini_json(raw)

    # Validate required fields
    if result.get("id") is None:
        logger.info("Channel %s: Gemini returned no unscheduled row", channel)
        return None

    if not result.get("date"):
        raise ValueError(f"Gemini returned no date for channel {channel}: {result}")

    # Enforce +05:30 suffix (safety net from n8n prompt rule)
    date_str = result["date"]
    if not date_str.endswith("+05:30"):
        logger.warning("Gemini date missing +05:30, fixing: %s", date_str)
        date_str = date_str.rstrip("Z").rstrip("+00:00") + "+05:30"
        result["date"] = date_str

    logger.info(
        "Channel %s: Gemini scheduled id=%s at %s",
        channel, result.get("id"), result.get("date"),
    )
    return result


# Re-export fallback rule-based helpers for direct use and testing
from backend.services._enrichment_rules import (
    enrich_title,
    enrich_tags,
    enrich_description,
    generate_first_comment,
    _parse_tags,
    _to_hashtag,
    enrich_post as rule_enrich_post,
)


def enrich_post(channel: str, title: str = "", description: str = "",
                tags: str = "", subscriber_count: int = 0) -> dict:
    """
    Called by upload_job when a post is being scheduled.
    Delegates to Gemini if API key is set; falls back to rule-based if not.
    """
    return rule_enrich_post(
        channel=channel,
        title=title,
        description=description,
        tags=tags,
        subscriber_count=subscriber_count,
    )


