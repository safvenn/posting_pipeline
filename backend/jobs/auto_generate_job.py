"""
Auto-Generate Job — Cloud Video Generation Pipeline

Runs daily at 9:00 AM IST via APScheduler (registered in main.py).
Works 100% in the cloud — laptop does NOT need to be on.

Flow:
  1. Read Google Sheet for all channels → find rows with prompt + auto_status=pending
  2. For each pending row: call fal.ai API → generate video
  3. Download video to /var/data/uploads/
  4. Insert Post into DB → existing serial queue handles the rest
     (watermark clean → Gemini SEO → YouTube upload → Instagram)
  5. Write auto_status=done back to Sheet
  6. Send Telegram notification

The job processes up to AUTO_GENERATE_MAX_PER_RUN rows per day
to avoid runaway costs if the Sheet has many pending rows.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings
from backend.database import SessionLocal
from backend.models import ChannelConfig, Post

logger = logging.getLogger(__name__)

# Max videos to generate per daily run (cost guard)
AUTO_GENERATE_MAX_PER_RUN = 5

# Global run state — prevents overlap if job is still running when next tick fires
_running = threading.Event()

# Track last run result for the /api/auto/status endpoint
# Protected by a lock since it is mutated from a daemon thread and read from the main thread
_last_run_result: dict = {}
_last_run_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Entry Point (called by APScheduler)
# ---------------------------------------------------------------------------

def run_auto_generate() -> None:
    """
    APScheduler entry point. Runs daily at 9 AM IST.
    Non-blocking: if already running, skips gracefully.
    """
    if _running.is_set():
        logger.warning("[AutoGen] Already running, skipping this trigger")
        return

    thread = threading.Thread(
        target=_run_auto_generate_sync,
        name="auto-generate-daily",
        daemon=True,
    )
    thread.start()


def trigger_now(channel: Optional[str] = None, limit: int = 1) -> dict:
    """
    Manual trigger for testing — runs immediately, returns status.
    Called by POST /api/auto/trigger endpoint.
    """
    if _running.is_set():
        return {"success": False, "message": "Auto-generate job is already running"}

    thread = threading.Thread(
        target=_run_auto_generate_sync,
        args=(channel, limit),
        name="auto-generate-manual",
        daemon=True,
    )
    thread.start()
    return {"success": True, "message": "Auto-generate job started in background"}


def get_last_run_result() -> dict:
    """Return a snapshot of the most recent run (thread-safe)."""
    with _last_run_lock:
        return dict(_last_run_result)


# ---------------------------------------------------------------------------
# Core Runner
# ---------------------------------------------------------------------------

def _run_auto_generate_sync(
    channel_override: Optional[str] = None,
    limit: int = AUTO_GENERATE_MAX_PER_RUN,
) -> None:
    """Synchronous implementation — runs in a daemon thread."""
    _running.set()
    run_start = datetime.now(timezone.utc)
    generated = 0
    failed = 0
    errors: list[str] = []

    try:
        logger.info("[AutoGen] 🚀 Starting daily auto-generate run at %s", run_start.isoformat())

        # 1. Get all active channels
        channels = _get_active_channels(channel_override)
        if not channels:
            logger.info("[AutoGen] No active channels configured.")
            _notify_telegram("⚠️ Auto-generate: No active channels configured.")
            return

        # 2. For each channel, fetch pending queue and generate
        for channel_key in channels:
            try:
                channel_generated, channel_failed, channel_errors = _process_channel(
                    channel_key, limit - generated
                )
                generated += channel_generated
                failed += channel_failed
                errors.extend(channel_errors)
                if generated >= limit:
                    logger.info("[AutoGen] Reached per-run limit of %d videos.", limit)
                    break
            except Exception as exc:
                err_msg = f"Channel '{channel_key}': {exc}"
                logger.exception("[AutoGen] %s", err_msg)
                errors.append(err_msg)
                failed += 1

        # 3. Summary notification
        duration_s = (datetime.now(timezone.utc) - run_start).total_seconds()
        summary = (
            f"🎬 Auto-Generate Complete\n"
            f"✅ Generated: {generated}\n"
            f"❌ Failed: {failed}\n"
            f"⏱️ Duration: {duration_s:.0f}s"
        )
        if errors:
            summary += f"\n⚠️ Errors:\n" + "\n".join(f"• {e}" for e in errors[:3])

        logger.info("[AutoGen] %s", summary.replace("\n", " | "))
        _notify_telegram(summary)

        with _last_run_lock:
            _last_run_result.update({
                "ran_at": run_start.isoformat(),
                "generated": generated,
                "failed": failed,
                "duration_s": round(duration_s, 1),
                "errors": errors[:5],
            })

    except Exception as exc:
        logger.exception("[AutoGen] Unexpected error in auto-generate job: %s", exc)
        _notify_telegram(f"❌ Auto-Generate ERROR: {exc}")
        with _last_run_lock:
            _last_run_result.update({"error": str(exc), "ran_at": run_start.isoformat()})
    finally:
        _running.clear()
        logger.info("[AutoGen] Job finished.")


# ---------------------------------------------------------------------------
# Per-Channel Processing
# ---------------------------------------------------------------------------

def _process_channel(channel: str, max_videos: int) -> tuple[int, int, list[str]]:
    """
    Process pending queue for one channel.
    Returns (generated_count, failed_count, error_messages).
    """
    from backend.services.sheets import get_all_rows, update_row_fields
    from backend.services.fal_service import generate_video, FalGenerationError, check_fal_configured

    if not check_fal_configured():
        raise RuntimeError(
            "FAL_API_KEY not configured. "
            "Add it in Render dashboard → Environment → FAL_API_KEY"
        )

    # Determine fal model from channel config or default
    model = _get_channel_model(channel)

    # Read pending rows from Sheet
    try:
        all_rows = get_all_rows(channel)
    except Exception as exc:
        raise RuntimeError(f"Could not read Google Sheet: {exc}") from exc

    pending = []
    for row in all_rows:
        prompt = str(row.get("prompt", "") or "").strip()
        if not prompt:
            continue
        auto_status = str(row.get("auto_status", "") or row.get("auto status", "")).strip().lower()
        scheduled = str(row.get("scheduled", "") or "").strip()
        upload_id = str(row.get("upload id", "") or row.get("upload_id", "")).strip()

        if auto_status in ("generating", "done", "uploaded"):
            continue
        if scheduled or upload_id:
            continue  # Already processed

        row_id = str(row.get("id", "")).strip()
        if not row_id:
            continue

        # Respect per-row model override
        row_model = str(row.get("model", "") or row.get("ai_model", "")).strip().lower() or model

        pending.append({
            "id": row_id,
            "prompt": prompt,
            "title": str(row.get("title", "") or "").strip(),
            "description": str(row.get("description", "") or "").strip(),
            "tags": str(row.get("tags", "") or "").strip(),
            "model": row_model,
        })

        if len(pending) >= max_videos:
            break

    if not pending:
        logger.info("[AutoGen] Channel '%s': no pending prompts.", channel)
        return 0, 0, []

    logger.info("[AutoGen] Channel '%s': %d pending prompt(s) to process.", channel, len(pending))
    generated = 0
    failed = 0
    errors = []

    for row in pending:
        row_id = row["id"]
        prompt = row["prompt"]
        row_model = row["model"]

        logger.info(
            "[AutoGen] Channel '%s' Row #%s: generating with %s — '%s...'",
            channel, row_id, row_model, prompt[:60]
        )

        # Mark as generating in Sheet immediately (prevents double-processing)
        try:
            update_row_fields(channel, row_id, {"auto_status": "generating"})
        except Exception as exc:
            logger.warning("[AutoGen] Could not mark row #%s as generating: %s", row_id, exc)

        # Generate the video via fal.ai
        video_url: Optional[str] = None
        try:
            video_url = generate_video(
                prompt=prompt,
                model=row_model,
                aspect_ratio="9:16",  # YouTube Shorts / Instagram Reels
                duration="5s",
            )
        except FalGenerationError as exc:
            err = f"Row #{row_id}: fal.ai generation failed — {exc}"
            logger.error("[AutoGen] %s", err)
            errors.append(err)
            failed += 1
            try:
                update_row_fields(channel, row_id, {"auto_status": "failed"})
            except Exception:
                pass
            _notify_telegram(f"❌ Auto-generate row #{row_id} failed:\n{exc}")
            continue

        # Download video to local storage
        video_path: Optional[Path] = None
        try:
            video_path = _download_video(video_url, channel, row_id)
        except Exception as exc:
            err = f"Row #{row_id}: download failed — {exc}"
            logger.error("[AutoGen] %s", err)
            errors.append(err)
            failed += 1
            try:
                update_row_fields(channel, row_id, {"auto_status": "failed"})
            except Exception:
                pass
            continue

        # Insert Post into DB and queue it through the pipeline
        try:
            post_id = _create_post(
                channel=channel,
                video_path=video_path,
                title=row.get("title") or prompt[:100],
                description=row.get("description", ""),
                tags=row.get("tags", ""),
                sheet_row_id=row_id,
                prompt=prompt,
            )
        except Exception as exc:
            err = f"Row #{row_id}: DB insert failed — {exc}"
            logger.error("[AutoGen] %s", err)
            errors.append(err)
            failed += 1
            try:
                update_row_fields(channel, row_id, {"auto_status": "failed"})
            except Exception:
                pass
            continue

        # Mark Sheet row as done
        try:
            update_row_fields(channel, row_id, {"auto_status": "done"})
        except Exception as exc:
            logger.warning("[AutoGen] Could not mark row #%s as done: %s", row_id, exc)

        generated += 1
        logger.info(
            "[AutoGen] ✅ Channel '%s' Row #%s → Post #%s queued (model=%s)",
            channel, row_id, post_id, row_model
        )
        _notify_telegram(
            f"🎬 Auto-generated video queued!\n"
            f"📋 Row #{row_id} | Post #{post_id}\n"
            f"📝 {prompt[:80]}{'...' if len(prompt) > 80 else ''}\n"
            f"🤖 Model: {row_model}"
        )

        # Trigger the pipeline queue immediately
        try:
            from backend.jobs.job_queue import run_serial_queue
            threading.Thread(target=run_serial_queue, name=f"queue-trigger-{post_id}", daemon=True).start()
        except Exception as exc:
            logger.warning("[AutoGen] Could not trigger queue for post #%s: %s", post_id, exc)

    return generated, failed, errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_channels(channel_override: Optional[str]) -> list[str]:
    """Return list of channel keys to process."""
    if channel_override:
        return [channel_override]

    channels = []
    try:
        with SessionLocal() as db:
            active = db.query(ChannelConfig).filter(ChannelConfig.is_active == True).all()
            channels = [c.key for c in active if c.key]
    except Exception as exc:
        logger.warning("[AutoGen] Could not query ChannelConfig: %s", exc)

    if not channels:
        # Fallback to known channel keys from config
        if settings.google_sheets_id_channel_a:
            channels.append("channel_a")
        if settings.google_sheets_id_channel_b:
            channels.append("channel_b")

    return channels


def _get_channel_model(channel: str) -> str:
    """Get the preferred fal.ai model for a channel from DB config or default."""
    try:
        with SessionLocal() as db:
            cfg = db.query(ChannelConfig).filter(
                ChannelConfig.key == channel,
                ChannelConfig.is_active == True,
            ).first()
            if cfg:
                # Use custom field if available, else default by channel
                model = getattr(cfg, "auto_generate_model", None) or ""
                if model.strip():
                    return model.strip().lower()
    except Exception:
        pass

    # Default: Kling v3 Pro for food/ASMR content
    return "kling"


def _download_video(video_url: str, channel: str, row_id: str) -> Path:
    """Download video from fal.ai CDN URL to local /var/data/uploads/.

    Security: download is size-capped at settings.max_download_size_mb to prevent
    disk exhaustion from unexpectedly large CDN responses.
    """
    upload_dir = settings.upload_path()
    filename = f"autogen_{channel}_{row_id}_{uuid.uuid4().hex[:8]}.mp4"
    dest = upload_dir / filename

    max_bytes = settings.max_download_size_mb * 1024 * 1024
    logger.info("[AutoGen] Downloading video from fal.ai CDN → %s (cap: %d MB)", dest, settings.max_download_size_mb)

    bytes_written = 0
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", video_url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        bytes_written += len(chunk)
                        if bytes_written > max_bytes:
                            raise FalGenerationError(
                                f"Download aborted: response exceeded {settings.max_download_size_mb} MB cap "
                                f"(wrote {bytes_written // 1024 // 1024} MB so far)"
                            )
                        f.write(chunk)
    except Exception:
        # Clean up partial file on any error to avoid leaving garbage on disk
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise

    size_mb = bytes_written / 1024 / 1024
    logger.info("[AutoGen] Downloaded %.1f MB → %s", size_mb, dest.name)
    return dest



def _create_post(
    channel: str,
    video_path: Path,
    title: str,
    description: str,
    tags: str,
    sheet_row_id: str,
    prompt: str,
) -> int:
    """Insert a Post record into the DB and return the new post ID."""
    with SessionLocal() as db:
        post = Post(
            channel=channel,
            title=title or prompt[:100],
            description=description or "",
            tags=tags or "",
            video_path=str(video_path),
            status="queued",
            scheduled_at=None,
            sheet_row_id=sheet_row_id,
        )
        db.add(post)
        db.commit()
        db.refresh(post)

        # Bind to next available Google Sheet slot
        try:
            from backend.services.sheets import bind_slot_and_update_sheet
            bind_slot_and_update_sheet(channel=channel, db=db, post=post, preferred_title=title)
        except Exception as exc:
            logger.warning("[AutoGen] Sheet slot bind failed for post #%s: %s", post.id, exc)

        return post.id


def _notify_telegram(message: str) -> None:
    """Send a Telegram notification if configured."""
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return

    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
    except Exception as exc:
        logger.warning("[AutoGen] Telegram notification failed: %s", exc)
