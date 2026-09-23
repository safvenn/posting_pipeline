"""
fal.ai Video Generation Service

Wraps the fal.ai REST API to generate AI videos from text prompts.
Runs entirely in the cloud — no browser, no laptop required.

Supported models (ranked by quality/cost):
  - fal-ai/kling-video/v3/pro    — Best for food/ASMR/cooking (~$0.14/5s)
  - fal-ai/veo-3                 — Google DeepMind, highest quality + native audio (~$0.25)
  - fal-ai/seedance-1-0-pro      — Fast + cinematic, great for nature (~$0.08/5s)

Usage:
    from backend.services.fal_service import generate_video
    video_url = generate_video(
        prompt="A chef cooking biryani, cinematic, close-up",
        model="kling",   # or "veo3" or "seedance"
    )
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional, Union

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Aliases → fal.ai App IDs
# ---------------------------------------------------------------------------

FAL_MODEL_MAP: dict[str, str] = {
    "kling":    "fal-ai/kling-video/v3/pro",
    "kling_v3": "fal-ai/kling-video/v3/pro",
    "veo3":     "fal-ai/veo-3",
    "veo":      "fal-ai/veo-3",
    "seedance": "fal-ai/seedance-1-0-pro",
    "fast":     "fal-ai/seedance-1-0-pro",
}

FAL_API_BASE = "https://queue.fal.run"
FAL_RESULT_BASE = "https://queue.fal.run"

# Polling config
POLL_INTERVAL_S = 8      # seconds between status checks
MAX_POLL_ATTEMPTS = 90   # 90 × 8s = 12 minutes max wait


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FalGenerationError(Exception):
    """Raised when fal.ai fails to generate a video."""


def generate_video(
    prompt: str,
    model: str = "kling",
    aspect_ratio: str = "9:16",   # 9:16 for Shorts/Reels
    duration: str = "5s",
    seed: Optional[int] = None,
) -> str:
    """
    Generate a video via fal.ai and return the direct video URL.

    Args:
        prompt:       Text description of the video.
        model:        Model alias: 'kling', 'veo3', 'seedance' (or full fal app ID).
        aspect_ratio: '9:16' for Shorts/Reels, '16:9' for landscape.
        duration:     '5s' or '10s'.
        seed:         Optional seed for reproducibility.

    Returns:
        Direct HTTPS URL to the generated MP4 video.

    Raises:
        FalGenerationError: on API failure, timeout, or missing output.
    """
    api_key = _get_api_key()

    # Resolve model alias → fal.ai app ID
    app_id = FAL_MODEL_MAP.get(model.lower(), model)
    logger.info("[FalAI] Generating video: model=%s prompt='%s...' aspect=%s",
                app_id, prompt[:60], aspect_ratio)

    # Submit the generation job
    request_id = _submit_job(api_key, app_id, prompt, aspect_ratio, duration, seed)
    logger.info("[FalAI] Job submitted: request_id=%s", request_id)

    # Poll until complete
    result = _poll_until_done(api_key, app_id, request_id)

    # Extract video URL from result
    video_url = _extract_video_url(result)
    if not video_url:
        raise FalGenerationError(f"fal.ai returned result but no video URL found: {result}")

    logger.info("[FalAI] ✅ Video ready: %s", video_url[:80])
    return video_url


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Get the fal.ai API key from settings, raise clearly if missing."""
    key = getattr(settings, "fal_api_key", "") or ""
    if not key.strip():
        raise FalGenerationError(
            "FAL_API_KEY is not configured. "
            "Add it to your Render environment variables: Settings → Environment → FAL_API_KEY"
        )
    return key.strip()


def _submit_job(
    api_key: str,
    app_id: str,
    prompt: str,
    aspect_ratio: str,
    duration: str,
    seed: Optional[int],
) -> Union[str, "_SyncResult"]:
    """Submit a generation job to fal.ai queue. Returns request_id or _SyncResult."""
    url = f"{FAL_API_BASE}/{app_id}"

    payload: dict = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }

    # Duration — not all models support this; add safely
    if duration and app_id not in ("fal-ai/veo-3",):
        payload["duration"] = duration

    if seed is not None:
        payload["seed"] = seed

    # Kling-specific parameters
    if "kling" in app_id:
        payload["negative_prompt"] = "blurry, low quality, watermark, text overlay, distorted"
        payload["cfg_scale"] = 0.5

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 201, 202):
        # Scrub response body before logging — it may echo back request data including prompt
        safe_body = re.sub(r'["\']?(?:key|token|api_key|secret)["\']?\s*:\s*["\'][^"\']{4,}["\']', '[REDACTED]', resp.text, flags=re.IGNORECASE)
        raise FalGenerationError(
            f"fal.ai job submit failed: HTTP {resp.status_code} — {safe_body[:200]}"
        )

    data = resp.json()
    request_id = data.get("request_id") or data.get("id")
    if not request_id:
        # Some models return the result synchronously
        if _extract_video_url(data):
            return _SyncResult(data)
        raise FalGenerationError(f"fal.ai returned no request_id: {list(data.keys())}")

    return request_id


class _SyncResult:
    """Sentinel wrapper when fal.ai returns synchronously."""
    def __init__(self, data: dict):
        self._data = data
    def __str__(self):
        return "_sync_"


def _poll_until_done(api_key: str, app_id: str, request_id: Union[str, "_SyncResult"]) -> dict:
    """Poll fal.ai status endpoint until the job is complete. Returns result dict."""
    # Handle synchronous responses
    if isinstance(request_id, _SyncResult):
        return request_id._data

    # Security: validate request_id before using it in a URL to prevent path traversal
    # fal.ai request IDs are UUIDs or alphanumeric slugs; reject anything else
    if not re.match(r'^[a-zA-Z0-9\-_]{4,128}$', str(request_id)):
        raise FalGenerationError(
            f"fal.ai returned invalid request_id format: {str(request_id)[:40]!r}"
        )

    status_url = f"{FAL_RESULT_BASE}/{app_id}/requests/{request_id}/status"
    result_url = f"{FAL_RESULT_BASE}/{app_id}/requests/{request_id}"

    headers = {"Authorization": f"Key {api_key}"}

    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_S)

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(status_url, headers=headers)
        except httpx.RequestError as e:
            logger.warning("[FalAI] Poll network error (attempt %d): %s", attempt + 1, e)
            continue

        if resp.status_code == 404:
            raise FalGenerationError(f"fal.ai request_id not found: {request_id}")

        if resp.status_code != 200:
            logger.warning("[FalAI] Poll HTTP %d (attempt %d), retrying...", resp.status_code, attempt + 1)
            continue

        status_data = resp.json()
        status = status_data.get("status", "")
        queue_pos = status_data.get("queue_position")

        elapsed = (attempt + 1) * POLL_INTERVAL_S
        if queue_pos is not None:
            logger.info("[FalAI] Status: %s | Queue pos: %s | Elapsed: %ds", status, queue_pos, elapsed)
        else:
            logger.info("[FalAI] Status: %s | Elapsed: %ds", status, elapsed)

        if status == "COMPLETED":
            # Fetch the full result
            with httpx.Client(timeout=30.0) as client:
                result_resp = client.get(result_url, headers=headers)
            if result_resp.status_code != 200:
                raise FalGenerationError(
                    f"fal.ai result fetch failed: HTTP {result_resp.status_code}"
                )
            return result_resp.json()

        elif status in ("FAILED", "ERROR", "CANCELLED"):
            error_msg = status_data.get("error", status_data.get("detail", status))
            raise FalGenerationError(f"fal.ai job {status}: {error_msg}")

        # Still IN_QUEUE or IN_PROGRESS — keep polling

    raise FalGenerationError(
        f"fal.ai generation timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_S}s "
        f"(request_id={request_id})"
    )


def _extract_video_url(result: dict) -> Optional[str]:
    """
    Extract the video URL from a fal.ai result dict.
    Handles multiple response shapes across models.
    """
    if not result:
        return None

    # Shape 1: { "video": { "url": "https://..." } }
    if isinstance(result.get("video"), dict):
        url = result["video"].get("url")
        if url:
            return url

    # Shape 2: { "video_url": "https://..." }
    if result.get("video_url"):
        return result["video_url"]

    # Shape 3: { "videos": [{ "url": "https://..." }] }
    videos = result.get("videos", [])
    if videos and isinstance(videos, list):
        first = videos[0]
        if isinstance(first, dict):
            return first.get("url") or first.get("video_url")
        if isinstance(first, str):
            return first

    # Shape 4: { "output": { "video": { "url": "..." } } }
    output = result.get("output", {})
    if isinstance(output, dict):
        v = output.get("video", {})
        if isinstance(v, dict):
            return v.get("url")

    # Shape 5: { "url": "..." }  (simple direct URL)
    if result.get("url", "").startswith("http"):
        return result["url"]

    return None


def check_fal_configured() -> bool:
    """Return True if FAL_API_KEY is set and non-empty."""
    try:
        _get_api_key()
        return True
    except FalGenerationError:
        return False
