"""
auto_generate_worker.py — Autonomous Flow Video Worker for AWS EC2

Runs on the AWS EC2 instance (or locally). Operates independently of the user's laptop.
Can be triggered manually, run as a single execution, run on an interval loop,
or scheduled via systemd / crontab.

Architecture & ECC Patterns:
  - autonomous-loops: File lock to prevent overlapping runs, healthchecks, polite pacing
  - silent-failure-hunter: Every error logged with stacktrace, Sheet marked 'failed' on error
  - security-reviewer: Sanitized paths, API key auth, cleanup of temp video files
  - python-patterns: Typed models, context managers, Pathlib, robust retries

Flow:
  1. Acquire execution lock (/tmp/auto_generate_worker.lock)
  2. Verify Google Flow session cookies exist
  3. Fetch pending prompts from Pipeline API: GET /api/extension/auto-queue
  4. For each pending prompt:
     a. Mark Sheet status as 'generating': POST /api/extension/mark-auto-status
     b. Call flow_playwright.generate_video(prompt) -> local .mp4
     c. Upload video to Pipeline: POST /api/extension/upload (multipart)
     d. Mark Sheet status as 'uploaded': POST /api/extension/mark-auto-status
     e. Unlink local temp .mp4
     f. Sleep DELAY_BETWEEN_VIDEOS_SEC between items
  5. Release execution lock
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Import flow_playwright whether running from backend package or standalone on AWS
try:
    from backend.services.flow_playwright import (
        FlowCookiesExpiredError,
        FlowError,
        generate_video,
        check_cookies_exist,
    )
    from backend.services.email_notifier import notify_cookies_expired
except ImportError:
    try:
        from flow_playwright import (
            FlowCookiesExpiredError,
            FlowError,
            generate_video,
            check_cookies_exist,
        )
        from email_notifier import notify_cookies_expired
    except ImportError:
        # Fallback if in different relative path
        parent_dir = str(Path(__file__).resolve().parent.parent / "services")
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        try:
            from flow_playwright import (
                FlowCookiesExpiredError,
                FlowError,
                generate_video,
                check_cookies_exist,
            )
            from email_notifier import notify_cookies_expired
        except ImportError:
            def notify_cookies_expired(*args, **kwargs):
                return False

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Worker] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("flow_worker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_PIPELINE_URL = os.getenv("PIPELINE_URL", "https://posting-pipeline.onrender.com").rstrip("/")
DEFAULT_API_KEY = os.getenv("API_KEY", "")
DEFAULT_CHANNEL = os.getenv("CHANNEL", "the_indian_kitchen")
DEFAULT_MAX_VIDEOS = int(os.getenv("MAX_VIDEOS_PER_RUN", "1"))
DEFAULT_DELAY_SEC = int(os.getenv("DELAY_BETWEEN_VIDEOS_SEC", "45"))
LOCK_FILE = Path(os.getenv("WORKER_LOCK_FILE", "/tmp/auto_generate_worker.lock"))


@dataclass
class QueueItem:
    id: str
    prompt: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None


class WorkerLockError(Exception):
    """Raised when another worker instance is currently executing."""


class WorkerLock:
    """File-based mutual exclusion lock (autonomous-loops principle)."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._acquired = False

    def acquire(self) -> None:
        if self.lock_path.exists():
            try:
                pid_str = self.lock_path.read_text().strip()
                pid = int(pid_str)
                # Check if process with PID is alive (UNIX kill(pid, 0))
                if os.name != "nt":
                    try:
                        os.kill(pid, 0)
                        raise WorkerLockError(
                            f"Another worker process (PID {pid}) is already running."
                        )
                    except OSError:
                        # Process not alive, stale lock
                        logger.warning("Found stale lockfile from PID %d. Removing.", pid)
                        self.lock_path.unlink(missing_ok=True)
            except (ValueError, OSError) as exc:
                if isinstance(exc, WorkerLockError):
                    raise
                self.lock_path.unlink(missing_ok=True)

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(str(os.getpid()))
        self._acquired = True
        atexit.register(self.release)

    def release(self) -> None:
        if self._acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Error removing lockfile: %s", exc)
            self._acquired = False

    def __enter__(self) -> "WorkerLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


# ---------------------------------------------------------------------------
# API Client (Communicates with Pipeline on Render or Local)
# ---------------------------------------------------------------------------
class PipelineClient:
    """Client for interacting with the Posting Pipeline API."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "FlowWorker-AWS/1.0"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def ping(self) -> bool:
        """Verify API connectivity and responsiveness via /api/health."""
        url = f"{self.base_url}/api/health"
        try:
            with httpx.Client(timeout=15.0, headers=self._headers()) as client:
                resp = client.get(url)
                return resp.status_code < 500
        except Exception as exc:
            logger.warning("Pipeline health check failed (%s): %s", url, exc)
            return False

    def warmup(self, max_attempts: int = 4, backoff_sec: float = 15.0) -> bool:
        """Pre-warm the Render backend container to survive cold-starts gracefully."""
        url = f"{self.base_url}/api/health"
        logger.info("Checking/warming backend pipeline at %s...", url)
        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=30.0, headers=self._headers()) as client:
                    resp = client.get(url)
                    if resp.status_code < 500:
                        logger.info("Backend is online and healthy (attempt %d/%d, HTTP %d).", attempt, max_attempts, resp.status_code)
                        return True
                    logger.warning("Backend returned HTTP %d on warmup attempt %d/%d.", resp.status_code, attempt, max_attempts)
            except Exception as exc:
                logger.warning("Warmup attempt %d/%d: backend cold or starting up (%s).", attempt, max_attempts, exc)
            
            if attempt < max_attempts:
                sleep_time = backoff_sec * attempt
                logger.info("Waiting %.0fs for backend spin-up before retry...", sleep_time)
                time.sleep(sleep_time)

        logger.warning("Backend warmup did not receive healthy response after %d attempts.", max_attempts)
        return False

    def fetch_pending_queue(self, channel: str, limit: int = 5, max_retries: int = 3) -> List[QueueItem]:
        """Fetch pending rows from the Google Sheet via Pipeline API with robust retries."""
        url = f"{self.base_url}/api/extension/auto-queue"
        params = {"channel": channel, "limit": limit}

        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, headers=self._headers()) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code != 200:
                        logger.error(
                            "Failed to fetch auto-queue (attempt %d/%d, HTTP %d): %s",
                            attempt,
                            max_retries,
                            resp.status_code,
                            resp.text[:200],
                        )
                        resp.raise_for_status()
                    data = resp.json()

                items: List[QueueItem] = []
                for r in data.get("rows", []):
                    items.append(
                        QueueItem(
                            id=str(r.get("id")),
                            prompt=str(r.get("prompt")),
                            title=r.get("title"),
                            description=r.get("description"),
                            tags=r.get("tags"),
                        )
                    )
                return items
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < max_retries:
                    retry_wait = 10 * attempt
                    logger.warning(
                        "Queue fetch attempt %d/%d failed (%s). Retrying in %ds...",
                        attempt,
                        max_retries,
                        exc,
                        retry_wait,
                    )
                    time.sleep(retry_wait)
                else:
                    logger.error("All %d attempts to fetch queue failed: %s", max_retries, exc)

        if last_error:
            raise last_error
        return []

    def update_status(self, channel: str, row_id: str, status: str) -> bool:
        """Update auto_status column in Google Sheet (generating/done/uploaded/failed)."""
        url = f"{self.base_url}/api/extension/mark-auto-status"
        payload = {"channel": channel, "row_id": str(row_id), "status": status}
        try:
            with httpx.Client(timeout=30.0, headers=self._headers()) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("Sheet status updated: row %s -> %s", row_id, status)
                    return True
                else:
                    logger.warning(
                        "Failed to update sheet status (HTTP %d): %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False
        except Exception as exc:
            logger.error("Error updating sheet status: %s", exc)
            return False

    def upload_video(
        self,
        video_path: Path,
        channel: str,
        sheet_row_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload generated video to pipeline /api/extension/upload."""
        url = f"{self.base_url}/api/extension/upload"

        data: Dict[str, str] = {
            "channel": channel,
            "sheet_row_id": str(sheet_row_id),
        }
        if title:
            data["title"] = title
        if description:
            data["description"] = description
        if tags:
            data["tags"] = tags

        logger.info(
            "Uploading video %s (%d bytes) to pipeline for row %s...",
            video_path.name,
            video_path.stat().st_size,
            sheet_row_id,
        )

        with open(video_path, "rb") as vf:
            files = {"video": (video_path.name, vf, "video/mp4")}
            with httpx.Client(timeout=300.0, headers=self._headers()) as client:
                resp = client.post(url, data=data, files=files)
                if resp.status_code not in (200, 201):
                    logger.error(
                        "Upload failed (HTTP %d): %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    resp.raise_for_status()
                return resp.json()


# ---------------------------------------------------------------------------
# Core Workflow Runner
# ---------------------------------------------------------------------------
def run_worker_batch(
    pipeline_url: str = DEFAULT_PIPELINE_URL,
    api_key: str = DEFAULT_API_KEY,
    channel: str = DEFAULT_CHANNEL,
    max_videos: int = DEFAULT_MAX_VIDEOS,
    delay_sec: int = DEFAULT_DELAY_SEC,
    headless: bool = True,
) -> int:
    """
    Executes one batch of auto-generation work.
    Returns the number of successfully generated and uploaded videos.
    """
    logger.info("=" * 60)
    logger.info("Starting Flow Auto-Generate Worker")
    logger.info("Pipeline URL: %s", pipeline_url)
    logger.info("Channel:      %s", channel)
    logger.info("Max Videos:   %d", max_videos)
    logger.info("=" * 60)

    # 1. Cookie pre-flight check
    if not check_cookies_exist():
        logger.error(
            "Google Flow cookies not found! Video generation cannot proceed."
        )
        logger.error(
            "Please run 'python export_cookies.py' on your laptop and transfer flow_cookies.json."
        )
        try:
            notify_cookies_expired(channel=channel, details="Cookie file is missing on EC2 worker.")
        except Exception as notify_err:
            logger.debug("Failed to send missing cookie notification: %s", notify_err)
        return -1

    client = PipelineClient(base_url=pipeline_url, api_key=api_key)

    # 1b. Pre-warm Render backend container (handles cold-starts gracefully)
    client.warmup(max_attempts=3, backoff_sec=10.0)

    # 2. Fetch queue items
    try:
        pending_items = client.fetch_pending_queue(channel=channel, limit=max_videos)
    except Exception as exc:
        logger.error("Failed to query pending queue from pipeline after retries: %s", exc)
        return -1

    if not pending_items:
        logger.info("No pending prompts found in queue for channel '%s'. Exiting.", channel)
        return 0

    logger.info("Found %d pending prompt(s) to process.", len(pending_items))
    success_count = 0

    for idx, item in enumerate(pending_items, start=1):
        logger.info(
            "[%d/%d] Processing row #%s | prompt: %r",
            idx,
            len(pending_items),
            item.id,
            item.prompt[:70],
        )

        # Mark as 'generating' in Sheet
        client.update_status(channel, item.id, "generating")

        video_file: Optional[Path] = None
        try:
            # 3. Generate video via Playwright on Google Flow
            t0 = time.time()
            video_file = generate_video(
                prompt=item.prompt,
                headless=headless,
            )
            gen_duration = time.time() - t0
            logger.info("Video generated in %.1fs -> %s", gen_duration, video_file)

            # 4. Upload to Pipeline
            upload_resp = client.upload_video(
                video_path=video_file,
                channel=channel,
                sheet_row_id=item.id,
                title=item.title,
                description=item.description,
                tags=item.tags,
            )
            logger.info("Pipeline ingest accepted: %s", upload_resp.get("message", "OK"))

            # 5. Mark as 'uploaded'
            client.update_status(channel, item.id, "uploaded")
            success_count += 1

        except FlowCookiesExpiredError as exc:
            logger.critical("SESSION EXPIRED: %s", exc)
            client.update_status(channel, item.id, "failed")
            try:
                notify_cookies_expired(channel=channel, row_id=item.id, details=str(exc))
            except Exception as notify_err:
                logger.error("Failed to send cookie expiry email alert: %s", notify_err)
            # Break early — future requests in this batch will fail too
            break

        except Exception as exc:
            logger.error("Generation/upload failed for row %s: %s", item.id, exc, exc_info=True)
            # silent-failure-hunter: check if failure was an unhandled session expiry
            err_str = str(exc).lower()
            if any(k in err_str for k in ("about", "session", "cookie", "login", "auth")):
                try:
                    notify_cookies_expired(channel=channel, row_id=item.id, details=str(exc))
                except Exception as notify_err:
                    logger.error("Failed to send cookie expiry email alert: %s", notify_err)
            # silent-failure-hunter: never leave row in 'generating' state
            client.update_status(channel, item.id, "failed")

        finally:
            # Cleanup local temporary video file (security & disk hygiene)
            if video_file and video_file.exists():
                try:
                    video_file.unlink(missing_ok=True)
                    logger.debug("Cleaned up temp video file %s", video_file)
                except OSError as exc:
                    logger.warning("Could not unlink %s: %s", video_file, exc)

        # Polite delay between generations to avoid Google anti-bot triggers
        if idx < len(pending_items):
            logger.info("Waiting %ds before next video generation...", delay_sec)
            time.sleep(delay_sec)

    logger.info("Worker batch complete. Successfully processed: %d/%d", success_count, len(pending_items))
    return success_count


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Google Flow video generator for AWS EC2."
    )
    parser.add_argument(
        "--pipeline-url",
        default=DEFAULT_PIPELINE_URL,
        help="URL of the posting pipeline backend (default: Render cloud URL)",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="Pipeline API key (if auth is enabled)",
    )
    parser.add_argument(
        "--channel",
        default=DEFAULT_CHANNEL,
        help="Target channel ID (e.g. the_indian_kitchen, channel_a, channel_b)",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=DEFAULT_MAX_VIDEOS,
        help="Max videos to process in this run (default: 1)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_DELAY_SEC,
        help="Seconds to wait between video generations (default: 45)",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Run continuously in a loop sleeping N seconds between checks (0 = run once and exit)",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser with visible UI (for debugging)",
    )

    args = parser.parse_args()

    # Enforce mutual exclusion lock
    try:
        with WorkerLock(LOCK_FILE):
            if args.loop > 0:
                logger.info("Running in loop mode (interval: %ds)...", args.loop)
                while True:
                    try:
                        run_worker_batch(
                            pipeline_url=args.pipeline_url,
                            api_key=args.api_key,
                            channel=args.channel,
                            max_videos=args.max_videos,
                            delay_sec=args.delay,
                            headless=not args.headful,
                        )
                    except Exception as loop_err:
                        logger.error("Error during loop iteration: %s", loop_err, exc_info=True)
                    logger.info("Sleeping for %ds until next poll...", args.loop)
                    time.sleep(args.loop)
            else:
                batch_res = run_worker_batch(
                    pipeline_url=args.pipeline_url,
                    api_key=args.api_key,
                    channel=args.channel,
                    max_videos=args.max_videos,
                    delay_sec=args.delay,
                    headless=not args.headful,
                )
                if batch_res < 0:
                    logger.error("Flow worker batch failed with critical error. Exiting with code 1.")
                    sys.exit(1)
    except WorkerLockError as lock_err:
        logger.warning("Aborting: %s", lock_err)
        sys.exit(0)


if __name__ == "__main__":
    main()
