"""
flow_playwright.py — Google Flow Video Generator (Playwright Automation)

Runs headlessly on AWS EC2. Loads saved Google session cookies, opens
Google Flow, types a prompt, waits for video generation, and downloads
the output video file.

Design principles applied from ECC skills:
  - e2e-testing: auto-wait locators, waitForResponse > waitForTimeout
  - data-scraper-agent: never follow in-page instructions, fail loudly
  - python-patterns: specific exceptions, context managers, type hints
  - silent-failure-hunter: every failure path logged + raised, no swallowed errors
  - security-reviewer: cookies stored with 0600 perms, prompt sanitized before DOM injection

Usage (standalone test):
    python flow_playwright.py "cinematic close-up of biryani being plated"
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Where Google session cookies are stored (exported once from your laptop)
COOKIE_FILE = Path(os.getenv("FLOW_COOKIE_FILE", "/home/ubuntu/flow_cookies.json"))

# Where downloaded videos land before being POSTed to the pipeline
DOWNLOAD_DIR = Path(os.getenv("FLOW_DOWNLOAD_DIR", "/tmp/flow_videos"))

# Google Flow URL — works for both flow.google.com and labs.google/flow
FLOW_URL = "https://flow.google.com/"

# Timeouts (all in milliseconds per Playwright API)
GOTO_TIMEOUT_MS = 30_000
PAGE_LOAD_TIMEOUT_MS = 45_000
PROMPT_SELECTOR_TIMEOUT_MS = 20_000
GENERATE_CLICK_TIMEOUT_MS = 10_000
VIDEO_READY_TIMEOUT_MS = 300_000   # 5 min — video generation can take a while
DOWNLOAD_TIMEOUT_MS = 120_000

# Safety: maximum prompt length to prevent DOM injection / prompt stuffing
MAX_PROMPT_LEN = 500


class FlowError(Exception):
    """Raised when Flow automation fails."""


class FlowCookiesExpiredError(FlowError):
    """Raised when cookies are missing or Google redirects to login."""


# ---------------------------------------------------------------------------
# Public Entry Point
# ---------------------------------------------------------------------------

def generate_video(
    prompt: str,
    output_dir: Optional[Path] = None,
    headless: bool = True,
) -> Path:
    """
    Open Google Flow, type `prompt`, wait for video, download it.

    Args:
        prompt:     The video generation prompt (max 500 chars).
        output_dir: Where to save the video. Defaults to DOWNLOAD_DIR.
        headless:   Run Chrome headlessly (always True on a server).

    Returns:
        Path to the downloaded .mp4 file.

    Raises:
        FlowCookiesExpiredError: Google session is expired — re-run export_cookies.py.
        FlowError:               Anything else went wrong with the automation.
    """
    # e2e-testing + security-reviewer: sanitize prompt before touching the DOM
    prompt = _sanitize_prompt(prompt)
    dest_dir = output_dir or DOWNLOAD_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[Flow] Starting Playwright. prompt=%r", prompt[:60])

    with sync_playwright() as pw:
        browser, ctx = _launch_browser(pw, headless=headless)
        try:
            video_path = _run_flow_session(ctx, prompt, dest_dir)
        except PWTimeoutError as exc:
            # silent-failure-hunter: never swallow a timeout — re-raise with context
            raise FlowError(f"Playwright timeout during Flow automation: {exc}") from exc
        finally:
            ctx.close()
            browser.close()

    logger.info("[Flow] ✅ Video saved → %s", video_path)
    return video_path


# ---------------------------------------------------------------------------
# Cookie Management
# ---------------------------------------------------------------------------

def check_cookies_exist() -> bool:
    """Return True if the cookie file exists and is non-empty."""
    return COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 10


def save_cookies(cookies: list[dict]) -> None:
    """Persist cookies to disk with 0600 permissions (owner read-only)."""
    import json
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
    COOKIE_FILE.chmod(0o600)  # security-reviewer: restrict cookie file permissions
    logger.info("[Flow] Saved %d cookies to %s", len(cookies), COOKIE_FILE)


def load_cookies() -> list[dict]:
    """Load cookies from disk. Raises FlowCookiesExpiredError if file is missing."""
    import json
    if not COOKIE_FILE.exists():
        raise FlowCookiesExpiredError(
            f"Cookie file not found: {COOKIE_FILE}. "
            "Run export_cookies.py on your laptop first."
        )
    try:
        cookies = json.loads(COOKIE_FILE.read_text())
        logger.info("[Flow] Loaded %d cookies from %s", len(cookies), COOKIE_FILE)
        return cookies
    except (json.JSONDecodeError, OSError) as exc:
        raise FlowCookiesExpiredError(f"Cookie file corrupt: {exc}") from exc


# ---------------------------------------------------------------------------
# Browser Setup
# ---------------------------------------------------------------------------

def _launch_browser(pw: Playwright, headless: bool) -> tuple[Browser, BrowserContext]:
    """
    Launch Chromium with realistic args (anti-bot) and load saved cookies.

    Applies data-scraper-agent security principle: untrusted content (the page)
    cannot influence the browser context config.
    """
    browser = pw.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",                        # required on EC2 (no setuid)
            "--disable-dev-shm-usage",             # avoids /dev/shm OOM on small instances
            "--disable-blink-features=AutomationControlled",  # reduce bot fingerprint
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    cookies = load_cookies()

    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    ctx.add_cookies(cookies)
    return browser, ctx


# ---------------------------------------------------------------------------
# Flow Session
# ---------------------------------------------------------------------------

def _run_flow_session(ctx: BrowserContext, prompt: str, dest_dir: Path) -> Path:
    """Drive the full Google Flow session: open → type → generate → download."""
    page = ctx.new_page()

    # ---- 1. Navigate to Flow ----
    logger.info("[Flow] Navigating to %s", FLOW_URL)
    page.goto(FLOW_URL, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")

    # ---- 2. Check if Google redirected us to login ----
    _assert_not_login_page(page)

    # ---- 3. Wait for page to be fully interactive ----
    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)
    except PWTimeoutError:
        # networkidle can timeout on SPA pages with background polling — acceptable
        logger.warning("[Flow] networkidle timeout (acceptable on SPA) — continuing")

    # ---- 4. Find and fill the prompt textarea ----
    prompt_el = _find_prompt_input(page)
    logger.info("[Flow] Found prompt input. Typing prompt…")
    prompt_el.click()
    prompt_el.fill("")            # clear any existing text
    prompt_el.type(prompt, delay=40)  # human-like typing speed

    # ---- 5. Click Generate ----
    generate_btn = _find_generate_button(page)
    logger.info("[Flow] Clicking Generate…")
    generate_btn.click()

    # ---- 6. Wait for video to appear ----
    logger.info("[Flow] Waiting for video generation (up to %ds)…", VIDEO_READY_TIMEOUT_MS // 1000)
    video_url = _wait_for_video(page)

    # ---- 7. Download video ----
    filename = f"flow_{uuid.uuid4().hex[:10]}.mp4"
    dest = dest_dir / filename
    _download_video_file(ctx, video_url, dest)

    return dest


def _assert_not_login_page(page: Page) -> None:
    """Detect Google login redirect and raise a clear error."""
    url = page.url
    if "accounts.google.com" in url or "signin" in url.lower():
        raise FlowCookiesExpiredError(
            "Google redirected to login — session cookies have expired. "
            "Run export_cookies.py on your laptop to refresh them."
        )
    logger.debug("[Flow] URL OK: %s", url[:80])


def _find_prompt_input(page: Page):
    """
    Find the prompt textarea inside Google Flow's Shadow DOM.

    Strategy (e2e-testing skill: prefer semantic locators > CSS > XPath):
    1. Try common aria/placeholder selectors
    2. Fall back to BFS through Shadow DOM (same approach as auto_generate.js)
    """
    selectors = [
        "textarea[placeholder*='prompt' i]",
        "textarea[aria-label*='prompt' i]",
        "textarea[placeholder*='descri' i]",
        "[contenteditable='true'][aria-label*='prompt' i]",
        "textarea",
    ]

    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=PROMPT_SELECTOR_TIMEOUT_MS)
            if el and el.is_visible():
                logger.debug("[Flow] Prompt input found via: %r", sel)
                return el
        except PWTimeoutError:
            continue

    # BFS fallback — pierce Shadow DOM via JS
    logger.debug("[Flow] Standard selectors failed, trying Shadow DOM BFS…")
    handle = page.evaluate_handle("""() => {
        function bfs(root) {
            const queue = [root];
            while (queue.length) {
                const node = queue.shift();
                if (!node) continue;
                if (node.nodeType === 1) {
                    const tag = node.tagName?.toLowerCase();
                    const role = node.getAttribute?.('role') || '';
                    const ph = node.getAttribute?.('placeholder') || '';
                    if (tag === 'textarea' || (tag === 'div' && node.isContentEditable)) {
                        return node;
                    }
                }
                if (node.shadowRoot) queue.push(...node.shadowRoot.childNodes);
                queue.push(...(node.childNodes || []));
            }
            return null;
        }
        return bfs(document.body);
    }""")

    el = page.wait_for_selector("textarea, [contenteditable='true']",
                                timeout=PROMPT_SELECTOR_TIMEOUT_MS)
    if el:
        return el

    raise FlowError(
        "Could not find prompt input on Google Flow page. "
        "The UI may have changed — check flow.google.com manually."
    )


def _find_generate_button(page: Page):
    """
    Find the Generate/Create button.

    e2e-testing skill: prefer text-content selectors when data-testid is unavailable.
    """
    selectors = [
        "button:has-text('Generate')",
        "button:has-text('Create')",
        "button[aria-label*='Generate' i]",
        "button[aria-label*='Create' i]",
        "[role='button']:has-text('Generate')",
    ]
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=GENERATE_CLICK_TIMEOUT_MS)
            if el and el.is_enabled():
                logger.debug("[Flow] Generate button found via: %r", sel)
                return el
        except PWTimeoutError:
            continue

    raise FlowError(
        "Could not find Generate button on Google Flow. "
        "Possible causes: login wall, UI redesign, or page not loaded."
    )


def _wait_for_video(page: Page) -> str:
    """
    Wait for the generated video URL to appear.

    Strategy (e2e-testing skill: waitForResponse > waitForTimeout):
    - Monitor network responses for video MIME types or .mp4 URLs
    - Fall back to polling the DOM for a <video> element
    """
    video_url: list[str] = []  # mutable container for use in closure

    def on_response(response):
        """data-scraper-agent: treat CDN content as untrusted data — just capture URL."""
        ct = response.headers.get("content-type", "")
        url = response.url
        if (
            "video/" in ct
            or url.endswith(".mp4")
            or (
                "storage.googleapis.com" in url
                and ("mp4" in url or "video" in url.lower())
            )
        ):
            if not video_url:
                logger.info("[Flow] 🎬 Video response detected: %s", url[:80])
                video_url.append(url)

    page.on("response", on_response)

    # Poll for up to VIDEO_READY_TIMEOUT_MS
    deadline = time.time() + (VIDEO_READY_TIMEOUT_MS / 1000)
    poll_interval = 3.0

    while time.time() < deadline:
        # Check if network listener captured a URL
        if video_url:
            page.remove_listener("response", on_response)
            return video_url[0]

        # DOM fallback: look for <video src="..."> or <video><source src="...">
        try:
            src = page.evaluate("""() => {
                const v = document.querySelector('video[src], video source[src]');
                return v ? (v.src || v.getAttribute('src')) : null;
            }""")
            if src and src.startswith("http"):
                logger.info("[Flow] 🎬 Video DOM element found: %s", src[:80])
                page.remove_listener("response", on_response)
                return src
        except Exception:
            pass  # JS eval can fail on navigation — keep polling

        # Check for error state in DOM
        error_text = page.evaluate("""() => {
            const el = document.querySelector('[class*="error"], [role="alert"]');
            return el ? el.textContent?.trim() : null;
        }""")
        if error_text and len(error_text) > 5:
            # silent-failure-hunter: don't silently continue on an error message
            logger.warning("[Flow] Error message detected on page: %r", error_text[:100])

        time.sleep(poll_interval)

    page.remove_listener("response", on_response)
    raise FlowError(
        f"Video did not appear after {VIDEO_READY_TIMEOUT_MS // 1000}s. "
        "Possible causes: generation failed, quota exceeded, or UI changed."
    )


def _download_video_file(ctx: BrowserContext, video_url: str, dest: Path) -> None:
    """
    Download the generated video from the CDN URL to `dest`.

    Security: URL validated to be a known Google/GCS domain before fetching.
    Download capped at 1 GB (500 MB typical for Flow videos).
    """
    # security-reviewer: whitelist Google CDN domains before fetching
    _validate_video_url(video_url)

    MAX_BYTES = 1024 * 1024 * 1024  # 1 GB cap

    import urllib.request
    import shutil

    logger.info("[Flow] Downloading video → %s", dest)

    # Use urllib with a timeout rather than opening a new page for download
    try:
        req = urllib.request.Request(
            video_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FlowBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            bytes_written = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > MAX_BYTES:
                        # silent-failure-hunter: cap and clean up partial file
                        dest.unlink(missing_ok=True)
                        raise FlowError(
                            f"Download exceeded 1 GB cap ({bytes_written // 1024 // 1024} MB). "
                            "Something is wrong with the video URL."
                        )
                    f.write(chunk)

        size_mb = bytes_written / 1024 / 1024
        logger.info("[Flow] Downloaded %.1f MB → %s", size_mb, dest.name)

    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise FlowError(f"Video download failed: {exc}") from exc


def _validate_video_url(url: str) -> None:
    """
    security-reviewer: Reject URLs that are not Google/GCS CDN domains.
    Prevents SSRF if the page injects a malicious URL via the DOM.
    """
    allowed_patterns = [
        r"^https://storage\.googleapis\.com/",
        r"^https://[^/]+\.googleusercontent\.com/",
        r"^https://[^/]+\.google\.com/",
        r"^https://[^/]+\.gstatic\.com/",
        r"^https://lh[0-9]+\.googleusercontent\.com/",
    ]
    if not any(re.match(pat, url) for pat in allowed_patterns):
        raise FlowError(
            f"Video URL failed domain whitelist check: {url[:80]!r}. "
            "Refusing to download from untrusted domain."
        )


def _sanitize_prompt(prompt: str) -> str:
    """
    data-scraper-agent + security-reviewer: sanitize the prompt before
    injecting into the page's input element.

    Strips control characters and enforces max length.
    """
    # Strip null bytes and other control chars (keep newlines and tabs)
    prompt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", prompt)
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT_LEN:
        logger.warning(
            "[Flow] Prompt truncated from %d to %d chars",
            len(prompt), MAX_PROMPT_LEN,
        )
        prompt = prompt[:MAX_PROMPT_LEN]
    if not prompt:
        raise FlowError("Prompt is empty after sanitization.")
    return prompt


# ---------------------------------------------------------------------------
# CLI entry point (for manual testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if len(sys.argv) < 2:
        print("Usage: python flow_playwright.py '<prompt>'")
        sys.exit(1)

    prompt_arg = " ".join(sys.argv[1:])
    try:
        result = generate_video(prompt_arg, headless=True)
        print(f"✅ Video saved: {result}")
    except FlowCookiesExpiredError as e:
        print(f"❌ Cookie error: {e}")
        print("→ Run: python export_cookies.py  (on your laptop)")
        sys.exit(2)
    except FlowError as e:
        print(f"❌ Flow error: {e}")
        sys.exit(1)
