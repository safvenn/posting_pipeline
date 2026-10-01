"""
create_profile.py — One-time Google Flow profile creator (run on LAPTOP)

Why this works better than cookies/storage-state JSON:
  - A persistent browser profile stores the FULL browser state:
    cookies, IndexedDB, localStorage, service workers, and cache.
  - Google's session (OSID/LSID) lasts months when tied to a full profile
    because it looks like a returning real user's browser.
  - A storage_state JSON snapshot misses IndexedDB/localStorage and can
    be invalidated server-side in 1-8 days when Google sees it reused from
    a different IP (laptop → EC2).

What this script does:
  1. Opens a real Chromium window (headed) pointing at a fresh profile dir.
  2. You navigate to flow.google.com and log in manually (including 2FA).
  3. Once you press Enter, it:
       a. Saves the full persistent profile to ./google_profile/
       b. Exports a flow_studio_auth.json snapshot from INSIDE the Flow studio
       c. SCPs both to your EC2 instance automatically

Usage:
    python create_profile.py

Requirements:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Configuration — edit these to match your EC2
# ---------------------------------------------------------------------------
EC2_HOST = os.getenv("WORKER_SSH_HOST", "13.49.226.26")
EC2_USER = os.getenv("WORKER_SSH_USER", "ubuntu")
EC2_KEY  = os.getenv(
    "WORKER_SSH_KEY_PATH",
    r"c:\Desktop\youtube Aauto\n8n-safvenn-key-pair.pem",
)

# Local paths (on your laptop)
PROFILE_DIR = Path("./google_profile")
AUTH_FILE   = Path("./flow_studio_auth.json")

# Remote paths (on EC2)
EC2_PROFILE_DIR = "/home/ubuntu/google_profile"
EC2_AUTH_FILE   = "/home/ubuntu/flow_studio_auth.json"

# Target URL — Flow studio landing
FLOW_URL = "https://flow.google.com/"

# ---------------------------------------------------------------------------
# Anti-detection browser args (same as flow_playwright.py)
# ---------------------------------------------------------------------------
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]


def find_chrome_executable() -> str | None:
    """Find the real Chrome binary on Windows/Linux/Mac."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for p in candidates:
        if Path(p).exists():
            return str(p)
    return None


def create_profile() -> None:
    """Open headed Chrome, let user log in, save profile + auth state."""
    print("\n" + "=" * 65)
    print("  Google Flow — Persistent Profile Creator")
    print("=" * 65)

    if PROFILE_DIR.exists():
        print(f"\n⚠️  Profile directory already exists: {PROFILE_DIR.resolve()}")
        confirm = input("   Overwrite / refresh it? [y/N] ").strip().lower()
        if confirm != "y":
            print("   Aborted.")
            sys.exit(0)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    chrome_exe = find_chrome_executable()
    if chrome_exe:
        print(f"✅ Real Chrome found: {chrome_exe}")
        print("   (Using real Chrome avoids Google's 'unsafe browser' block during login)")
    else:
        print("ℹ️  Real Chrome not detected — falling back to Playwright Chromium")

    print(f"\n📂 Profile directory: {PROFILE_DIR.resolve()}")
    print("\n🌐 Opening Google Flow in a HEADED browser window...")
    print("   → Log in with your Google account (marshmellosafwan@gmail.com).")
    print("   → Complete any 2FA / captcha steps normally.")
    print("   → Click 'Start Creating' / enter the Flow Studio canvas.")
    print("   → Once the dark studio and prompt editor are visible, press Enter.\n")

    with sync_playwright() as pw:
        launch_kwargs = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": False,
            "args": BROWSER_ARGS + ["--disable-extensions"],
            "ignore_default_args": ["--enable-automation"],
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
        }
        if chrome_exe:
            launch_kwargs["channel"] = "chrome"
        else:
            launch_kwargs["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            )

        ctx = pw.chromium.launch_persistent_context(**launch_kwargs)
        page = ctx.new_page()
        page.goto(FLOW_URL, timeout=30_000, wait_until="domcontentloaded")

        while True:
            input("\n>>> Press [ENTER] when you are fully inside the Flow Studio: ")
            current_url = page.url
            print(f"   Current page: {current_url}")

            if "accounts.google.com" in current_url or "signin" in current_url.lower():
                print("   Still logging in — complete Google login in browser, then press Enter.")
                continue

            if "/about" in current_url or current_url.rstrip("/") == FLOW_URL.rstrip("/"):
                print("   Still on Flow landing page — please click 'Start Creating', then press Enter.")
                continue

            # Check for studio prompt box
            try:
                page.wait_for_selector(".ProseMirror, [contenteditable='true'], textarea", timeout=5000)
                print("   ✅ Studio prompt box detected!")
                break
            except Exception:
                ans = input(
                    f"\n   Prompt box not detected yet on {current_url[:60]}.\n"
                    "   Are you inside the studio canvas? Type 'yes' to proceed, or press Enter to retry: "
                ).strip().lower()
                if ans in ("yes", "y"):
                    break

        # Export storage state (cookies + localStorage) from inside the studio
        print("\n💾 Exporting auth state from inside the studio...")
        try:
            ctx.storage_state(path=str(AUTH_FILE))
            print(f"   ✅ Saved: {AUTH_FILE.resolve()}")
        except Exception as exc:
            print(f"   ⚠️  Could not export auth state: {exc}")
            print("       The persistent profile will still be used as fallback.")

        ctx.close()

    print(f"\n✅ Profile saved: {PROFILE_DIR.resolve()}")
    _display_cookie_summary()


def _display_cookie_summary() -> None:
    """Print a quick summary of what was captured."""
    if AUTH_FILE.exists():
        try:
            data = json.loads(AUTH_FILE.read_text())
            cookies = data.get("cookies", [])
            key_cookies = {"OSID", "__Secure-OSID", "LSID", "__Host-1PLSID", "__Host-3PLSID", "SID"}
            important = [c["name"] for c in cookies if c["name"] in key_cookies]
            print(f"\n📋 Auth state: {len(cookies)} cookies captured.")
            print(f"   Key Google session cookies found: {sorted(set(important)) or '(none found — check you logged in fully)'}")
        except Exception:
            pass


def upload_to_ec2() -> None:
    """SCP the profile directory and auth JSON to EC2."""
    key_path = Path(EC2_KEY)
    if not key_path.exists():
        print(f"\n⚠️  SSH key not found at: {key_path}")
        print("   Skipping EC2 upload. Copy files manually:")
        print(f"     scp -r {PROFILE_DIR.resolve()} {EC2_USER}@{EC2_HOST}:{EC2_PROFILE_DIR}")
        if AUTH_FILE.exists():
            print(f"     scp {AUTH_FILE.resolve()} {EC2_USER}@{EC2_HOST}:{EC2_AUTH_FILE}")
        return

    print(f"\n📤 Uploading to EC2 ({EC2_USER}@{EC2_HOST})...")

    ssh_opts = [
        "-i", str(key_path),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
    ]

    # Upload auth JSON first (fast)
    if AUTH_FILE.exists():
        print(f"   → Uploading {AUTH_FILE.name}...")
        result = subprocess.run(
            ["scp"] + ssh_opts + [str(AUTH_FILE), f"{EC2_USER}@{EC2_HOST}:{EC2_AUTH_FILE}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"   ✅ {AUTH_FILE.name} uploaded.")
        else:
            print(f"   ❌ Upload failed: {result.stderr.strip()}")

    # Upload full profile dir (rsync for speed/resumability)
    print(f"   → Uploading google_profile/ (this may take 30-60s)...")
    rsync_cmd = [
        "rsync", "-avz", "--delete",
        "-e", f"ssh {' '.join(ssh_opts)}",
        f"{PROFILE_DIR}/",
        f"{EC2_USER}@{EC2_HOST}:{EC2_PROFILE_DIR}/",
    ]
    # Fall back to scp if rsync not available
    try:
        result = subprocess.run(rsync_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"   ✅ google_profile/ uploaded via rsync.")
        else:
            raise RuntimeError(result.stderr)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"   rsync unavailable/failed ({exc}), falling back to scp...")
        result = subprocess.run(
            ["scp", "-r"] + ssh_opts + [str(PROFILE_DIR), f"{EC2_USER}@{EC2_HOST}:{EC2_PROFILE_DIR}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"   ✅ google_profile/ uploaded via scp.")
        else:
            print(f"   ❌ scp failed: {result.stderr.strip()}")
            print(f"       Manual command: scp -r -i \"{key_path}\" {PROFILE_DIR}/ {EC2_USER}@{EC2_HOST}:{EC2_PROFILE_DIR}/")


def main() -> None:
    create_profile()

    print("\n" + "-" * 60)
    upload = input("📤 Upload to EC2 now? [Y/n] ").strip().lower()
    if upload in ("", "y", "yes"):
        upload_to_ec2()
        print("\n🎉 Done! Your EC2 worker will use the new persistent profile.")
        print("   Session longevity: months (instead of 1-8 days with cookies).")
    else:
        print("\n📋 Manual upload commands:")
        key_path = Path(EC2_KEY)
        print(f"   scp -i \"{key_path}\" {AUTH_FILE} {EC2_USER}@{EC2_HOST}:{EC2_AUTH_FILE}")
        print(f"   scp -r -i \"{key_path}\" {PROFILE_DIR}/ {EC2_USER}@{EC2_HOST}:{EC2_PROFILE_DIR}/")

    print("\n✅ Next daily run at 9:00 AM IST will automatically use the new session.")


if __name__ == "__main__":
    main()
