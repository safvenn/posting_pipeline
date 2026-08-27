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
    "You are an elite, top-tier YouTube Shorts & Reels Content Creator and Viral SEO Specialist. "
    "Your mission is to produce human-crafted, high-CTR, algorithmically boosted metadata tailored specifically "
    "to the unique dish and action in the video. "
    "CRITICAL: Avoid generic bot-like titles. Vary your title styles dynamically across posts. "
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
    """Build the full Gemini prompt with diverse hook styles, SEO keywords, and viral engagement rules."""
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

    recent_titles_sample = [v.get("snippet", {}).get("title", "") for v in recent_videos[:8] if v.get("snippet", {}).get("title")]

    if target_row:
        row_context_section = f"""TARGET GOOGLE SHEET ROW (ENRICH AND PROCESS THIS EXACT SELECTED ROW):
{json.dumps(target_row, indent=2)}

SELECTION INSTRUCTION:
- You MUST enrich and generate optimized metadata specifically for the TARGET ROW above (ID: {target_row.get('id')}).
- Extract and utilize its exact `id`, `title`, `description`, and `tags`.
- In your JSON response, set `"id": {json.dumps(target_row.get('id'))}`."""
    else:
        row_context_section = f"""GOOGLE SHEET ROWS (find and process ONLY the first unscheduled row):
{json.dumps(all_rows, indent=2)}

SELECTION INSTRUCTION:
- Select ONLY the first sheet row where `scheduled` is empty or null.
- Extract its `id`, `title`, `description`, `tags`."""

    return f"""You are an elite viral YouTube Shorts & Instagram Reels growth strategist.
Channel data and context have been fetched below:

CHANNEL DETAILS:
{json.dumps(channel_details)}

RECENT UPLOADS ON THIS CHANNEL (DO NOT COPY OR REPEAT THESE TITLE FORMULAS):
{json.dumps(recent_titles_sample, indent=2)}

{row_context_section}

CURRENT IST TIME: {current_ist}

══════════════════════════════════════════════════════════════════════════════════
VIRAL TITLE & CONTENT GENERATION RULES (CREATIVE, VARIED & HUMAN HOOKS)
══════════════════════════════════════════════════════════════════════════════════

1. ANTI-REPETITION & TITLE DIVERSITY (CRITICAL):
   - NEVER repeat the same opening phrase (e.g. do NOT use "World's Tiniest..." or "Satisfying Tiny..." for every video).
   - Analyze recent upload titles above and pick a FRESH, DISTINCT hook angle from the style matrix below:
     • Style A (Sensory / Sizzle Hook): "The Sizzle On This Mini [Dish]! ASMR Cooking #shorts"
     • Style B (Curiosity / Question Hook): "Would You Try Making [Dish] On A Micro Clay Stove? #shorts"
     • Style C (Extreme Detail / Scale Hook): "Every Single Detail Of [Dish] In 1:12 Miniature! #shorts"
     • Style D (Street Food Vibe Hook): "Midnight Mini Street Food: Crispy [Dish] Sizzle #shorts"
     • Style E (Hypnotic / Relaxing Hook): "Oddly Relaxing [Dish] Preparation On Tiny Fire 🔥 #shorts"
     • Style F (Crunch & Texture Hook): "Wait For That Golden [Dish] Crunch! ASMR #shorts"
     • Style G (Challenge / Reaction Hook): "Cooking Authentic [Dish] For Ants?! Tiny Kitchen #shorts"
   - Length: 50–70 characters. High punchiness, emotional trigger, exact dish name, and ends with "#shorts".

2. ENGAGEMENT-BOOSTED DESCRIPTION (Multi-Layered Viral Structure):
   - Layer 1 (Sensory Storytelling): 2–3 mouthwatering sentences describing the authentic sizzling aroma, spice pop, and micro cookware precision.
   - Layer 2 (Search Keyword SEO): Natural injection of high-search phrases (e.g., "authentic miniature Indian cooking ASMR", "relaxing kitchen sounds", "satisfying tiny food preparation").
   - Layer 3 (Comment Driving Question): Interactive question tailored specifically to the dish (e.g. "Rate this tiny [dish] from 1–10! 😋👇 What should we shrink next?").
   - Layer 4 (Channel Subscribe CTA): "{subscribe_cta_example}"
   - Layer 5 (Hashtags): 6–8 curated hashtags (#shorts #miniaturecooking #tinyfood #asmrcooking #indianfood #satisfying #foodie #[dishname]).

3. HIGH-REACH SEO TAGS:
   - Merge the dish tags with high-intent keywords from: {seo_pool}.
   - Return a clean array of 15–20 distinct tags (dish-specific, genre-specific, and broad Shorts tags).

4. PINNED FIRST COMMENT (Interactive Reply Catalyst):
   - Short (under 160 characters), engaging question with 1 emoji to spark lively comment section discussions.

5. SCHEDULING (VIRAL PEAK SLOTS):
   - Slot A: 12:30 PM IST (Lunch Peak)
   - Slot B: 06:30 PM IST (Prime Evening Peak)
   - Must be strictly in the future (>30 min from current time) and have at least 5 HOURS minimum spacing gap from recent videos.

══════════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT (STRICT VALID JSON ONLY - NO CODE FENCES - NO MARKDOWN):
══════════════════════════════════════════════════════════════════════════════════
{{
  "id": "{target_row.get('id') if target_row else 1}",
  "title": "Distinctive Viral Title Tailored To The Dish #shorts",
  "description": "Sensory-rich description with keywords, engagement question, CTA, and #hashtags",
  "tags": ["miniature cooking", "tiny food", "asmr cooking", "indian food asmr", "shorts"],
  "firstComment": "What miniature dish should we cook next? Top voted comment wins! 👩‍🍳👇",
  "date": "YYYY-MM-DDTHH:MM:SS+05:30"
}}
- Date must always be formatted as 'YYYY-MM-DDTHH:MM:SS+05:30', strictly inside Slot A or Slot B, strictly in the future."""


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
    logger.info("Calling Gemini (%s) for channel %s enrichment", settings.gemini_model, channel)
    try:
        raw = _call_gemini(prompt)
        logger.debug("Gemini raw output: %.500s", raw)
        result = _parse_gemini_json(raw)
    except Exception as exc:
        logger.error(
            "Gemini enrichment failed for channel %s with model %s: %s",
            channel, settings.gemini_model, exc, exc_info=True
        )
        raise

    # Validate required fields
    if result.get("id") is None and not target_post and not target_row_id:
        logger.info("Channel %s: Gemini returned no unscheduled row", channel)
        return None

    if result.get("id") is None and target_post:
        result["id"] = getattr(target_post, "sheet_row_id", None)

    # Validate and enforce authoritative future slot time
    from backend.services.scheduler_logic import pick_next_slot
    from backend.database import SessionLocal
    with SessionLocal() as db_session:
        try:
            slot = pick_next_slot(channel, db_session)
            result["date"] = slot.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        except Exception as exc:
            logger.warning("Could not pick next slot during Gemini enrichment: %s", exc)

    logger.info(
        "Channel %s: Gemini enriched id=%s at %s",
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


