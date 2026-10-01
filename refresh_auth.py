"""
refresh_auth.py — Auto-refresh flow_studio_auth.json from the persistent profile (EC2)

WHY THIS EXISTS:
  The persistent profile (google_profile/) lasts months on EC2, but
  flow_studio_auth.json (the JSON snapshot used by flow_playwright.py Priority 1)
  can drift out of sync as cookies rotate inside the profile.

  This script re-exports a fresh flow_studio_auth.json from the live profile
  WITHOUT needing your laptop. It runs headlessly on EC2 every N days.

HOW TO USE:
  # Run manually:
  python refresh_auth.py

  # Schedule via crontab on EC2 (every 3 days at 3 AM):
  0 3 */3 * * cd /home/ubuntu/flow-worker && python refresh_auth.py >> /home/ubuntu/refresh_auth.log 2>&1

REQUIREMENTS:
  pip install playwright
  playwright install chromium

ENV VARS (read from .env automatically):
  FLOW_PROFILE_DIR  — path to persistent profile (default: /home/ubuntu/google_profile)
  FLOW_AUTH_FILE    — output JSON path (default: /home/ubuntu/flow_studio_auth.json)
  FLOW_URL          — Google Flow URL (default: https://flow.google.com/)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent / ".env"
    if _env.exists():
        load_dotenv(_env)
    _env2 = Path("/home/ubuntu/flow-worker/.env")
    if _env2.exists():
        load_dotenv(_env2)
except ImportError:
    pass

from playwright.sync_api import (
    BrowserContext,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [refresh_auth] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("refresh_auth")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROFILE_DIR  = Path(os.getenv("FLOW_PROFILE_DIR", "/home/ubuntu/google_profile"))
AUTH_FILE    = Path(os.getenv("FLOW_AUTH_FILE",   "/home/ubuntu/flow_studio_auth.json"))
FLOW_URL     = os.getenv("FLOW_URL", "https://flow.google.com/")

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--disable-setuid-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
]

# ---------------------------------------------------------------------------
# Helper import
# ---------------------------------------------------------------------------

def _get_flow_helpers():
    """Import auto-login and credential helpers from flow_playwright."""
    try:
        from backend.services.flow_playwright import _auto_login_google, _get_google_credentials
        return _auto_login_google, _get_google_credentials
    except ImportError:
        pass
    try:
        from flow_playwright import _auto_login_google, _get_google_credentials
        return _auto_login_google, _get_google_credentials
    except ImportError:
        return None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def refresh_auth() -> bool:
    """
    Launch a headless browser using the persistent profile, navigate to Flow,
    and export a fresh storage_state JSON.

    Returns True if refresh succeeded, False otherwise.
    """
    # Check if profile exists, or if we can auto-login with credentials
    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        logger.info("Persistent profile not found at %s. Checking for credentials...", PROFILE_DIR)
        auto_login_fn, creds_fn = _get_flow_helpers()
        if creds_fn and auto_login_fn:
            email, password, _ = creds_fn()
            if email and password:
                logger.info("Credentials found in .env — performing autonomous initial login...")
                with sync_playwright() as pw:
                    ctx = auto_login_fn(pw, headless=True)
                    ctx.close()
                return True

        logger.error(
            "Persistent profile not found and no credentials set in .env. "
            "Please configure FEMAIL and FPASS in .env or run create_profile.py."
        )
        return False

    logger.info("Starting auth refresh using profile: %s", PROFILE_DIR)

    with sync_playwright() as pw:
        try:
            ctx: BrowserContext = pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
                args=BROWSER_ARGS + ["--disable-extensions"],
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
        except Exception as exc:
            logger.error("Failed to launch persistent context: %s", exc)
            return False

        try:
            page = ctx.new_page()

            logger.info("Navigating to %s ...", FLOW_URL)
            page.goto(FLOW_URL, timeout=30_000, wait_until="domcontentloaded")
            time.sleep(3)

            current_url = page.url
            logger.info("Current URL after navigation: %s", current_url[:100])

            # Check for session expiry (login redirect)
            if "accounts.google.com" in current_url or "signin" in current_url.lower():
                logger.warning("Session has expired (redirected to %s). Checking for auto-relogin...", current_url[:60])
                auto_login_fn, creds_fn = _get_flow_helpers()
                if creds_fn and auto_login_fn:
                    email, password, _ = creds_fn()
                    if email and password:
                        logger.info("Credentials found — triggering autonomous relogin...")
                        ctx.close()
                        new_ctx = auto_login_fn(pw, headless=True)
                        new_ctx.close()
                        logger.info("✅ Autonomous relogin successful during auth refresh!")
                        return True

                logger.critical(
                    "⚠️  Session expired and FEMAIL/FPASS credentials not configured. "
                    "Set FEMAIL and FPASS in .env for autonomous login."
                )
                _take_debug_screenshot(page, "/tmp/refresh_auth_login_redirect.png")
                return False

            # Try to enter the studio if on landing page (triggers studio-specific cookies)
            studio_page = page
            if "/about" in current_url or current_url.rstrip("/") == FLOW_URL.rstrip("/"):
                logger.info("On landing page — attempting to enter studio to get OSID/LSID...")
                try:
                    start_btn = page.locator(
                        'button[aria-label*="Create with Google Flow"], '
                        'button[aria-label*="Start Creating"], '
                        'button:has-text("Start Creating"), '
                        'button:has-text("Get started"), '
                        'button:has-text("Try Flow"), '
                        'a:has-text("Start Creating"), '
                        'a:has-text("Open project")'
                    ).first
                    start_btn.wait_for(state="visible", timeout=10_000)
                    try:
                        with ctx.expect_page(timeout=10_000) as new_page_info:
                            start_btn.click()
                        studio_page = new_page_info.value
                    except Exception:
                        studio_page = ctx.pages[-1]

                    studio_page.wait_for_selector(
                        ".ProseMirror, [contenteditable='true']",
                        timeout=20_000,
                    )
                    logger.info("Inside studio — studio cookies now active.")
                    time.sleep(2)
                except PWTimeoutError:
                    logger.warning(
                        "Could not enter studio (button not found or timed out). "
                        "Exporting auth from current page."
                    )
                except Exception as exc:
                    logger.warning("Studio entry attempt: %s", exc)

            # Re-check for login redirect after studio entry attempt
            current_url = studio_page.url
            if "accounts.google.com" in current_url or "signin" in current_url.lower():
                logger.warning("Session expired after studio entry. Checking for auto-relogin...")
                auto_login_fn, creds_fn = _get_flow_helpers()
                if creds_fn and auto_login_fn:
                    email, password, _ = creds_fn()
                    if email and password:
                        ctx.close()
                        new_ctx = auto_login_fn(pw, headless=True)
                        new_ctx.close()
                        return True
                return False

            # Export fresh storage state
            logger.info("Exporting fresh storage state → %s", AUTH_FILE)
            ctx.storage_state(path=str(AUTH_FILE))

            # Verify key cookies in the exported file
            exported = json.loads(AUTH_FILE.read_text())
            cookies = exported.get("cookies", [])
            cookie_names = {c["name"] for c in cookies}
            key_cookies = cookie_names & {"OSID", "LSID", "SID", "SSID", "HSID"}

            logger.info(
                "✅ Exported %d cookies. Key session cookies found: %s",
                len(cookies),
                sorted(key_cookies) or ["(none — session may have partially expired)"],
            )

            if not key_cookies:
                logger.warning(
                    "No OSID/LSID/SID cookies found in export. "
                    "The session may be partially expired. flow_playwright.py will fall back "
                    "to the persistent profile directory which should still work."
                )

            # Write a metadata sidecar so workers know when the last refresh happened
            meta = {
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "key_cookies_present": sorted(key_cookies),
                "total_cookies": len(cookies),
                "profile_dir": str(PROFILE_DIR),
            }
            meta_path = AUTH_FILE.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(meta, indent=2))
            logger.info("Metadata written to %s", meta_path)

            return bool(key_cookies)

        except Exception as exc:
            logger.error("Unexpected error during auth refresh: %s", exc, exc_info=True)
            return False

        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _take_debug_screenshot(page, path: str) -> None:
    """Save a debug screenshot; swallow errors."""
    try:
        page.screenshot(path=path)
        logger.info("Debug screenshot saved: %s", path)
    except Exception:
        pass


def main() -> None:
    logger.info("=" * 55)
    logger.info("Flow Auth Refresher — %s", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 55)

    ok = refresh_auth()

    if ok:
        logger.info("✅ Auth refresh completed successfully.")
        sys.exit(0)
    else:
        logger.error("❌ Auth refresh FAILED — manual intervention required.")
        logger.error("   Run create_profile.py on your laptop and re-upload google_profile/.")
        sys.exit(1)


if __name__ == "__main__":
    main()
