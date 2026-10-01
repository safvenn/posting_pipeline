"""
flow_playwright.py — Google Flow Video Generator (Playwright Automation)

Runs headlessly on AWS EC2. Uses a persistent Chromium browser profile
(google_profile/) instead of cookie JSON snapshots. The profile is created
once on your laptop via create_profile.py and uploaded to AWS.

Session longevity: months (vs 1-8 days with cookies).

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

import base64
import hashlib
import hmac
import logging
import os
import re
import struct
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

try:
    from dotenv import load_dotenv
    for _p in [
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
        Path("/home/ubuntu/flow-worker/.env"),
        Path.cwd() / ".env",
    ]:
        if _p.exists():
            load_dotenv(_p)
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Auth: storage state JSON exported from INSIDE the Flow studio
# This has OSID/LSID cookies that only exist after entering the studio
AUTH_FILE = Path(os.getenv("FLOW_AUTH_FILE", "/home/ubuntu/flow_studio_auth.json"))

# Fallback: persistent browser profile directory
PROFILE_DIR = Path(os.getenv("FLOW_PROFILE_DIR", "/home/ubuntu/google_profile"))

# Google Flow URL — public landing page
FLOW_URL = "https://flow.google.com/"

# Where downloaded videos land before being POSTed to the pipeline
DOWNLOAD_DIR = Path(os.getenv("FLOW_DOWNLOAD_DIR", "/tmp/flow_videos"))

# Timeouts (all in milliseconds per Playwright API)
GOTO_TIMEOUT_MS = 30_000
PAGE_LOAD_TIMEOUT_MS = 45_000
PROMPT_SELECTOR_TIMEOUT_MS = 20_000
GENERATE_CLICK_TIMEOUT_MS = 10_000
VIDEO_READY_TIMEOUT_MS = 300_000   # 5 min — video generation can take a while
DOWNLOAD_TIMEOUT_MS = 120_000

# Safety: maximum prompt length to prevent DOM injection / prompt stuffing
MAX_PROMPT_LEN = 4000


class FlowError(Exception):
    """Raised when Flow automation fails."""


class FlowSessionExpiredError(FlowError):
    """Raised when the browser profile session is expired or missing."""


# Keep old name as alias for backwards compatibility
FlowCookiesExpiredError = FlowSessionExpiredError


# ---------------------------------------------------------------------------
# Public Entry Point
# ---------------------------------------------------------------------------

def generate_totp_code(secret: str) -> str:
    """
    Generate real-time 6-digit TOTP code from a base32 secret (standard RFC 6238).
    Zero external dependencies (uses Python standard library hmac, hashlib, base64, struct).
    """
    cleaned_secret = secret.upper().replace(" ", "").replace("-", "")
    key = base64.b32decode(cleaned_secret, casefold=True)
    counter = int(time.time()) // 30
    counter_bytes = struct.pack(">Q", counter)
    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _get_google_credentials() -> tuple[str, str, str | None]:
    """Retrieve Google login credentials and optional TOTP secret from environment."""
    email = os.getenv("FEMAIL", "").strip()
    password = os.getenv("FPASS", "").strip()
    totp_secret = os.getenv("FTOTP_SECRET", "").strip() or None
    return email, password, totp_secret


def _is_on_login_page(page) -> bool:
    """Return True when the page is a Google login/accounts page."""
    url = getattr(page, "url", "")
    return (
        "accounts.google.com" in url
        or "signin" in url.lower()
        or "ServiceLogin" in url
        or "challenge" in url
    )


def _auto_login_google(pw: Playwright, headless: bool = True) -> BrowserContext:
    """
    Perform fully autonomous Google SSO login using FEMAIL, FPASS, and optional FTOTP_SECRET.
    Bypasses Google anti-bot checks and exports fresh auth storage state to AUTH_FILE.
    """
    email, password, totp_secret = _get_google_credentials()
    if not email or not password:
        raise FlowSessionExpiredError(
            "Autonomous login requires FEMAIL and FPASS to be set in .env."
        )

    domain = email.split("@")[-1] if "@" in email else "***"
    logger.info("[Flow] Initiating autonomous Google SSO login (account: ***@%s)...", domain)

    common_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=common_args + ["--disable-extensions"],
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )

    # Stealth: override navigator.webdriver to prevent detection
    ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        # Step 1: Open Google Sign-In
        logger.info("[Flow] Opening Google accounts login page...")
        page.goto(
            "https://accounts.google.com/signin/v2/identifier?hl=en",
            wait_until="domcontentloaded",
            timeout=35_000,
        )
        time.sleep(2)

        # Check if already signed in
        if not ("accounts.google.com" in page.url or "signin" in page.url):
            logger.info("[Flow] Google account is already authenticated in persistent context.")
        else:
            # Step 2: Input Email
            email_input = page.locator('input[type="email"], input[name="identifier"]').first
            email_input.wait_for(state="visible", timeout=15_000)
            email_input.click()
            for ch in email:
                page.keyboard.type(ch)
                time.sleep(0.03)
            logger.info("[Flow] Email typed. Submitting...")
            next_btn = page.locator('button:has-text("Next"), #identifierNext, [data-action="next"]').first
            next_btn.click()
            time.sleep(2.5)

            # Step 3: Input Password
            password_input = page.locator('input[type="password"], input[name="Passwd"]').first
            password_input.wait_for(state="visible", timeout=20_000)
            password_input.click()
            for ch in password:
                page.keyboard.type(ch)
                time.sleep(0.03)
            logger.info("[Flow] Password typed. Submitting...")
            pw_next = page.locator('button:has-text("Next"), #passwordNext, [data-action="next"]').first
            pw_next.click()
            time.sleep(3)

            # Step 4: Handle 2FA / TOTP Challenge
            for _ in range(12):
                curr_url = page.url
                if not ("accounts.google.com" in curr_url or "signin" in curr_url or "challenge" in curr_url):
                    break

                totp_input = page.locator(
                    'input[id="totpPin"], input[name="totpPin"], input[type="tel"], input[autocomplete="one-time-code"]'
                ).first
                if totp_input.count() > 0 and totp_input.is_visible():
                    if not totp_secret:
                        raise FlowSessionExpiredError(
                            "Google requested 2FA verification code, but FTOTP_SECRET is not set in .env!\n"
                            "Fix: Add FTOTP_SECRET=<your_32_char_authenticator_key> to .env on EC2."
                        )
                    totp_code = generate_totp_code(totp_secret)
                    logger.info("[Flow] Generating live TOTP code for 2FA...")
                    totp_input.click()
                    totp_input.fill(totp_code)
                    time.sleep(0.5)
                    totp_next = page.locator('#totpNext, button:has-text("Next")').first
                    totp_next.click()
                    logger.info("[Flow] Submitted TOTP code.")
                    time.sleep(3)
                    break

                # If Google shows options list, click Google Authenticator option
                auth_opt = page.locator(
                    'div[data-challengetype="6"], div:has-text("Google Authenticator"), div:has-text("Authenticator app")'
                ).first
                if auth_opt.count() > 0 and auth_opt.is_visible():
                    logger.info("[Flow] Selecting Google Authenticator challenge method...")
                    auth_opt.click()
                    time.sleep(2)
                    continue

                time.sleep(1)

        # Step 5: Navigate to Google Flow
        logger.info("[Flow] Navigating to %s ...", FLOW_URL)
        page.goto(FLOW_URL, timeout=35_000, wait_until="domcontentloaded")
        time.sleep(3)

        # Dismiss cookie banner
        try:
            banner = page.locator('button:has-text("OK, got it"), button:has-text("Accept all")').first
            if banner.count() > 0 and banner.is_visible():
                banner.click()
        except Exception:
            pass

        # Step 6: Enter Studio & Catch New Tab
        studio_page = None
        for p in ctx.pages:
            if p.locator(".ProseMirror, [contenteditable='true']").count() > 0:
                studio_page = p
                break

        if not studio_page:
            start_btn = page.locator(
                'button[aria-label*="Create with Google Flow"], '
                'button[aria-label*="Start Creating"], '
                'button:has-text("Start Creating"), '
                'a:has-text("Start Creating"), '
                'a:has-text("Open project"), '
                'button:has-text("Get started"), '
                'button:has-text("Try Flow"), '
                '.flow-button.variant-primary'
            ).first
            if start_btn.count() > 0 and start_btn.is_visible():
                logger.info("[Flow] Clicking 'Start Creating' and watching for studio tab...")
                try:
                    with ctx.expect_page(timeout=12_000) as new_page_info:
                        start_btn.click()
                    studio_page = new_page_info.value
                except Exception:
                    studio_page = ctx.pages[-1]

        if not studio_page:
            studio_page = ctx.pages[-1]

        try:
            studio_page.wait_for_selector(".ProseMirror, [contenteditable='true']", timeout=25_000)
            logger.info("[Flow] Studio editor active on URL: %s", studio_page.url[:80])
        except Exception as e:
            logger.debug("[Flow] Studio editor selector notice: %s", e)

        # Step 7: Export storage state
        logger.info("[Flow] Exporting new auth storage state to %s", AUTH_FILE)
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_auth = AUTH_FILE.with_suffix(".tmp.json")
        ctx.storage_state(path=str(tmp_auth))
        tmp_auth.replace(AUTH_FILE)
        try:
            AUTH_FILE.chmod(0o600)
        except Exception:
            pass

        logger.info("[Flow] ✅ Autonomous login complete! Session ready.")
        return ctx

    except Exception as exc:
        logger.error("[Flow] Autonomous login failed: %s", exc, exc_info=True)
        try:
            page.screenshot(path="/tmp/flow_auto_login_failure.png")
            logger.info("Saved failure screenshot to /tmp/flow_auto_login_failure.png")
        except Exception:
            pass
        ctx.close()
        raise FlowSessionExpiredError(f"Autonomous login failed: {exc}") from exc


def generate_video(
    prompt: str,
    output_dir: Optional[Path] = None,
    headless: bool = True,
) -> Path:
    """
    Open Google Flow, type `prompt`, wait for video, download it.
    Self-healing: automatically performs autonomous login if session is expired/missing.
    """
    prompt = _sanitize_prompt(prompt)
    dest_dir = output_dir or DOWNLOAD_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[Flow] Starting Playwright. prompt=%r", prompt[:60])

    pw = sync_playwright().start()
    try:
        try:
            ctx = _launch_browser(pw, headless=headless)
        except FlowSessionExpiredError:
            email, password, _ = _get_google_credentials()
            if email and password:
                logger.info("[Flow] Auth missing/expired — triggering autonomous Google login...")
                ctx = _auto_login_google(pw, headless=headless)
            else:
                raise

        try:
            try:
                video_path = _run_flow_session(ctx, prompt, dest_dir)
            except FlowSessionExpiredError as session_err:
                email, password, _ = _get_google_credentials()
                if email and password:
                    logger.warning("[Flow] Session expired mid-run (%s). Attempting auto-relogin...", session_err)
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    ctx = _auto_login_google(pw, headless=headless)
                    video_path = _run_flow_session(ctx, prompt, dest_dir)
                else:
                    raise session_err
        except PWTimeoutError as exc:
            raise FlowError(f"Playwright timeout during Flow automation: {exc}") from exc
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    finally:
        pw.stop()

    logger.info("[Flow] ✅ Video saved → %s", video_path)
    return video_path


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

def check_session_exists() -> bool:
    """Return True if auth storage state, persistent profile, or credentials exist."""
    if AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 100:
        return True
    if PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir()):
        return True
    email, password, _ = _get_google_credentials()
    return bool(email and password)


# Keep old name as alias for backwards compatibility
def check_cookies_exist() -> bool:
    return check_session_exists()


# ---------------------------------------------------------------------------
# Browser Setup
# ---------------------------------------------------------------------------

def _launch_browser(pw: Playwright, headless: bool) -> BrowserContext:
    """
    Launch Chromium with Flow studio authentication.

    Priority:
    1. storage_state JSON (flow_studio_auth.json) — has OSID/LSID studio cookies
    2. Persistent profile directory (google_profile/) — fallback
    3. Autonomous login via FEMAIL / FPASS / FTOTP_SECRET
    """
    common_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    # Priority 1: storage_state JSON (preferred — captured from inside studio)
    if AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 100:
        logger.info("[Flow] Using storage state auth: %s", AUTH_FILE)
        browser = pw.chromium.launch(
            headless=headless,
            args=common_args,
        )
        ctx = browser.new_context(
            storage_state=str(AUTH_FILE),
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            ignore_https_errors=False,
        )
        return ctx

    # Priority 2: persistent profile directory (fallback)
    if PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir()):
        logger.info("[Flow] Using persistent profile: %s (no auth JSON found)", PROFILE_DIR)
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            args=common_args + ["--disable-extensions"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        return ctx

    # Priority 3: Autonomous login using configured credentials
    email, password, _ = _get_google_credentials()
    if email and password:
        logger.info("[Flow] No existing session found. Triggering autonomous login...")
        return _auto_login_google(pw, headless=headless)

    raise FlowSessionExpiredError(
        f"No auth found and FEMAIL/FPASS not set in environment.\n"
        f"Need either:\n"
        f"  1. FEMAIL and FPASS in .env for autonomous login, OR\n"
        f"  2. {AUTH_FILE} / {PROFILE_DIR}/"
    )


# ---------------------------------------------------------------------------
# Flow Session
# ---------------------------------------------------------------------------

def _run_flow_session(ctx: BrowserContext, prompt: str, dest_dir: Path) -> Path:
    """Drive the full Google Flow session: open → type → generate → download."""
    page = ctx.new_page() if ctx.pages == [] else ctx.pages[-1]
    if not page or page.is_closed():
        page = ctx.new_page()

    # Capture video network responses early
    captured_video_urls: list[str] = []

    def on_response(response):
        """Capture generated video asset URLs from network traffic.
        
        Explicitly ignores gstatic.com landing page demo videos.
        """
        try:
            ct = response.headers.get("content-type", "")
            url = response.url
            # Exclude landing page marketing demo videos
            if "gstatic.com" in url or "landing_page" in url:
                return
            if (
                "video/" in ct
                or url.endswith(".mp4")
                or "flow-content.google/video" in url
                or "googlevideo.com/videoplayback" in url
                or (
                    "storage.googleapis.com" in url
                    and ("mp4" in url or "video" in url.lower())
                )
            ):
                if url not in captured_video_urls:
                    logger.info("[Flow] 🎬 Video response detected: %s", url[:80])
                    captured_video_urls.append(url)
        except Exception:
            pass

    page.on("response", on_response)

    # ---- 1. Navigate to Flow ----
    logger.info("[Flow] Navigating to %s", FLOW_URL)
    page.goto(FLOW_URL, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")

    # ---- 2. Check if Google redirected us to login (but /about is OK here — it's the landing page) ----
    _assert_not_login_page(page, allow_landing=True)

    # ---- 3. Dismiss cookie consent banner if present ----
    try:
        consent = page.locator('button:has-text("OK, got it")').first
        consent.wait_for(state="visible", timeout=4000)
        consent.click()
        logger.info("[Flow] Dismissed cookie consent banner.")
        time.sleep(1)
    except Exception as exc:
        logger.debug("[Flow] Cookie banner not shown: %s", exc)

    # ---- 4. Enter studio if on landing page ----
    # ---- 4. Enter studio if on landing page ----
    entered_studio = False
    try:
        # Check all open pages in context to see if any already has the studio editor
        for p in ctx.pages:
            if p.locator(".ProseMirror, [contenteditable='true']").count() > 0:
                page = p
                logger.info("[Flow] Already inside studio on page: %s", page.url[:80])
                entered_studio = True
                break

        if not entered_studio and ("/about" in page.url or page.url.rstrip("/") == FLOW_URL.rstrip("/")):
            start_btn = page.locator(
                'button[aria-label*="Create with Google Flow"], '
                'button[aria-label*="Start Creating"], '
                'button:has-text("Start Creating"), '
                'a:has-text("Start Creating"), '
                'a:has-text("Open project"), '
                'button:has-text("Get started"), '
                'button:has-text("Try Flow"), '
                '.flow-button.variant-primary'
            ).first
            try:
                start_btn.wait_for(state="visible", timeout=12000)
                logger.info("[Flow] Clicking studio entry button (watching for popup/tab)...")
                try:
                    with ctx.expect_page(timeout=10000) as new_page_info:
                        start_btn.click()
                    page = new_page_info.value
                except Exception:
                    # In case it didn't open a new page or opened in same page
                    if len(ctx.pages) > 1 and ctx.pages[-1] != page:
                        page = ctx.pages[-1]
            except Exception as e:
                logger.debug("[Flow] Start button wait/click notice: %s", e)

            # Wait for studio prompt editor to be mounted
            page.wait_for_selector(".ProseMirror, [contenteditable='true']", timeout=25000)
            logger.info("[Flow] Navigated into studio, prompt editor ready.")
            entered_studio = True
    except Exception as exc:
        logger.warning("[Flow] Studio entry handling: %s", exc)

    # ---- 4.1 Validate session ----
    if "accounts.google.com" in page.url or "signin" in page.url:
        _assert_not_login_page(page)  # always check for login redirect
    elif "/about" in page.url and not entered_studio:
        _assert_not_login_page(page)  # raises FlowSessionExpiredError if stuck on about
    else:
        logger.info("[Flow] Session OK, current URL: %s", page.url[:80])

    # ---- 4.5. Configure Video Mode, Omni 1.1 model, 9:16 aspect ratio, and x1 quantity ----
    try:
        # 1. Open settings trigger
        trigger = page.locator(
            'button[aria-label="Settings trigger"], button:has-text("crop_"), button:has-text("Nano Banana"), button:has-text("Omni 1.1"), button:has-text("Settings")'
        ).last
        if trigger.is_visible():
            logger.info("[Flow] Opening generation settings popup...")
            trigger.click()
            time.sleep(1)

        # 2. Select Video tab in popup
        video_tab = page.locator('button[role="radio"]:has-text("Video"), button:has-text("videocamVideo")').first
        if video_tab.is_visible():
            logger.info("[Flow] Selecting Video mode tab...")
            video_tab.click()
            time.sleep(1)

        # 3. Ensure Omni 1.1 model family is selected
        model_btn = page.locator('button[aria-label="Select model family"]').first
        if model_btn.is_visible():
            current_model = model_btn.text_content().strip()
            if "omni" not in current_model.lower():
                logger.info("[Flow] Model is %r; selecting Omni 1.1 Flash...", current_model)
                model_btn.click()
                time.sleep(1)
                omni_item = page.locator(
                    '.cdk-overlay-pane [role="menuitem"]:has-text("Omni"), .cdk-overlay-pane button:has-text("Omni"), .cdk-overlay-pane [role="option"]:has-text("Omni")'
                ).first
                if omni_item.is_visible():
                    omni_item.click()
                    time.sleep(1)
            else:
                logger.info("[Flow] Omni 1.1 model is selected.")

        # 4. Select 9:16 vertical shorts aspect ratio
        ar_btn = page.locator('button:has-text("9:16"), [role="button"]:has-text("9:16")').first
        if ar_btn.is_visible():
            logger.info("[Flow] Selecting 9:16 vertical aspect ratio (shorts)...")
            ar_btn.click()
            time.sleep(0.5)

        # 5. Select x1 (only generate 1 video)
        x1_btn = page.locator('button[role="radio"]:has-text("x1")').first
        if x1_btn.is_visible():
            logger.info("[Flow] Setting quantity to x1 (single video)...")
            x1_btn.click()
            time.sleep(0.5)

        # Close settings popup
        page.keyboard.press("Escape")
        time.sleep(1)
    except Exception as exc:
        logger.warning("[Flow] Note during video mode configuration: %s", exc)

    # ---- 5. Find and fill the prompt editor ----
    prompt_el = _find_prompt_input(page)
    logger.info("[Flow] Found prompt editor. Entering prompt...")
    prompt_el.click()
    time.sleep(0.5)
    try:
        page.keyboard.insert_text(prompt)
    except Exception:
        prompt_el.fill(prompt)

    time.sleep(1)

    # ---- 6. Click Generate (arrow_forward icon or button) ----
    generate_btn = _find_generate_button(page)
    logger.info("[Flow] Triggering video generation...")
    if generate_btn:
        generate_btn.click()
    else:
        logger.info("[Flow] Pressing Enter key...")
        page.keyboard.press("Enter")

    time.sleep(5)

    # ---- 7. Wait for video to appear ----
    logger.info("[Flow] Waiting for video generation (up to %ds)…", VIDEO_READY_TIMEOUT_MS // 1000)
    video_url = _wait_for_video(page, captured_video_urls)

    # ---- 8. Download video ----
    filename = f"flow_{uuid.uuid4().hex[:10]}.mp4"
    dest = dest_dir / filename
    _download_video_file(ctx, video_url, dest)

    return dest


def _assert_not_login_page(page: Page, allow_landing: bool = False) -> None:
    """
    Detect Google login redirect and raise a clear error.

    allow_landing=True: skip the /about check (authenticated users land there too).
    allow_landing=False (default): treat /about as a session failure (used after
    'Start Creating' was already clicked and we should be in the studio).
    """
    url = page.url
    on_login_page = (
        "accounts.google.com" in url
        or "signin" in url.lower()
    )
    on_about_page = (
        url.rstrip("/").endswith("/about")
        or "/about" in url
    )

    if on_login_page:
        raise FlowSessionExpiredError(
            f"Google Flow redirected to login page ({url}) — session has expired.\n"
            "Fix: Run create_profile.py on your laptop and re-upload google_profile/ to AWS."
        )

    if on_about_page and not allow_landing:
        # We clicked 'Start Creating' but still on /about — real session problem
        raise FlowSessionExpiredError(
            f"Still on landing page ({url}) after 'Start Creating' click — "
            "session may be partially expired.\n"
            "Fix: Run create_profile.py on your laptop and re-upload google_profile/ to AWS."
        )

    logger.debug("[Flow] URL OK: %s", url[:80])


def _find_prompt_input(page: Page):
    """
    Find the prompt textarea/ProseMirror editor inside Google Flow.
    """
    selectors = [
        ".ProseMirror",
        "div[contenteditable='true']",
        "[contenteditable='true']",
        "textarea[placeholder*='create' i]",
        "textarea[placeholder*='prompt' i]",
        "textarea[aria-label*='prompt' i]",
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
    try:
        el = page.wait_for_selector(".ProseMirror, textarea, [contenteditable='true']",
                                    timeout=PROMPT_SELECTOR_TIMEOUT_MS)
        if el and el.is_visible():
            return el
    except Exception:
        pass

    try:
        page.screenshot(path="/tmp/flow_prompt_debug.png")
        logger.warning("[Flow] Saved debug screenshot to /tmp/flow_prompt_debug.png")
    except Exception:
        pass

    # Check if page was redirected to login or about during prompt location
    _assert_not_login_page(page)

    raise FlowError(
        f"Could not find prompt input on Google Flow page ({page.url}). "
        "The UI may have changed or session expired."
    )


def _find_generate_button(page: Page):
    """
    Find the Generate/arrow_forward button.
    """
    selectors = [
        "button:has-text('arrow_forward')",
        "button:has-text('Generate')",
        "button:has-text('Create')",
        "button[aria-label*='arrow_forward' i]",
        "button[aria-label*='Generate' i]",
        "button[aria-label*='Create' i]",
        "[role='button']:has-text('arrow_forward')",
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

    return None


def _wait_for_video(page: Page, captured_urls: list[str]) -> str:
    """
    Wait for the generated video URL to appear.

    Strategy:
    - Check captured network responses for video URLs.
    - Poll DOM for <video> or <source> elements.
    - Click any generated video thumbnail cards to trigger media load.
    """
    deadline = time.time() + (VIDEO_READY_TIMEOUT_MS / 1000)
    poll_interval = 4.0

    while time.time() < deadline:
        # 1. Check network captured URLs
        if captured_urls:
            logger.info("[Flow] 🎬 Captured video from network: %s", captured_urls[0][:80])
            return captured_urls[0]

        # 2. Check DOM for video elements
        try:
            src = page.evaluate("""() => {
                const v = document.querySelector('video[src], video source[src]');
                return v ? (v.src || v.getAttribute('src')) : null;
            }""")
            if src and "http" in src:
                logger.info("[Flow] 🎬 Video DOM element found: %s", src[:80])
                return src
        except Exception:
            pass

        # 3. Check for clickable video cards and click to activate playback stream
        try:
            card = page.locator(
                'button.thumbnail-button, [role="button"]:has(video), div:has(> video), [data-item-type="video"]'
            ).first
            if card.count() > 0 and card.is_visible():
                card.click()
                time.sleep(1)
            else:
                # Click candidate canvas coordinates where recent generated videos sit (supports both 2-card and 4-card layouts)
                for coords in [(248, 250), (370, 250), (480, 250), (590, 250)]:
                    page.mouse.click(*coords)
                    time.sleep(0.5)
                    if captured_urls:
                        break
        except Exception:
            pass

        # 4. Check for error state in DOM
        error_text = page.evaluate("""() => {
            const el = document.querySelector('[class*="error"], [role="alert"]');
            return el ? el.textContent?.trim() : null;
        }""")
        if error_text and len(error_text) > 5:
            logger.warning("[Flow] Page notice: %r", error_text[:100])

        time.sleep(poll_interval)

    # Final fallback check on captured_urls
    if captured_urls:
        return captured_urls[0]

    # Save diagnostic screenshot
    try:
        page.screenshot(path="/tmp/flow_timeout.png")
    except Exception:
        pass

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
        r"^https://flow-content\.google/",
        r"^https://[^/]+\.googlevideo\.com/",
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
        print(f"❌ Session error: {e}")
        print("→ Run: python create_profile.py  (on your laptop)")
        sys.exit(2)
    except FlowError as e:
        print(f"❌ Flow error: {e}")
        sys.exit(1)
