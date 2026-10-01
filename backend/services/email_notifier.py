"""
Email notification service for the automated worker and watermark pipeline.

Sends alert notifications (e.g., when Google Flow session cookies expire)
via standard SMTP (Gmail App Password, Outlook, AWS SES, etc.).
Zero external dependencies (uses Python standard library smtplib).
"""
from __future__ import annotations

import os
import smtplib
import logging
from email.message import EmailMessage
from typing import Optional
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
    if os.path.exists("/home/ubuntu/flow-worker/.env"):
        load_dotenv("/home/ubuntu/flow-worker/.env")
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587


def get_smtp_config() -> dict[str, str | int]:
    """Retrieve SMTP configuration from environment variables."""
    host = os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST).strip()
    port_str = os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip()
    try:
        port = int(port_str)
    except ValueError:
        port = DEFAULT_SMTP_PORT

    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    # Normalize Google 16-character App Passwords (remove spaces like 'abcd efgh ijkl mnop')
    if "gmail" in host.lower() and len(password.replace(" ", "")) == 16:
        password = password.replace(" ", "")

    # If NOTIFICATION_EMAIL_TO is not specified, default to the SMTP_USER
    recipient = os.getenv("NOTIFICATION_EMAIL_TO", user).strip()

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "recipient": recipient,
    }


def is_email_configured() -> bool:
    """Return True if SMTP sender credentials are configured."""
    cfg = get_smtp_config()
    return bool(cfg["user"] and cfg["password"] and cfg["recipient"])


def send_email(
    subject: str,
    text_content: str,
    html_content: Optional[str] = None,
    recipient_override: Optional[str] = None,
) -> bool:
    """
    Send an email via SMTP.

    Returns True if sent successfully, False otherwise.
    Never raises an exception — logs errors so it cannot crash the caller.
    """
    cfg = get_smtp_config()
    to_email = (recipient_override or cfg["recipient"]).strip()

    if not cfg["user"] or not cfg["password"] or not to_email:
        logger.warning(
            "[EmailNotifier] Cannot send email: SMTP credentials not fully configured "
            "(SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL_TO)."
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"YouTube Auto Pipeline <{cfg['user']}>"
    msg["To"] = to_email
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(text_content)

    if html_content:
        msg.add_alternative(html_content, subtype="html")

    try:
        host = str(cfg["host"])
        port = int(cfg["port"])

        if port == 465:
            # SSL
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.login(str(cfg["user"]), str(cfg["password"]))
                server.send_message(msg)
        else:
            # STARTTLS (port 587 default)
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(str(cfg["user"]), str(cfg["password"]))
                server.send_message(msg)

        logger.info("[EmailNotifier] Successfully sent notification email to %s (Subject: %r)", to_email, subject)
        return True

    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "[EmailNotifier] SMTP Authentication Failed: Check your SMTP_USER and SMTP_PASSWORD. "
            "For Gmail, use a 16-character Google App Password (not your normal password): %s",
            exc,
        )
        return False
    except Exception as exc:
        logger.error("[EmailNotifier] Failed to send email via %s:%s: %s", cfg["host"], cfg["port"], exc)
        return False


def notify_cookies_expired(
    channel: str = "the_indian_kitchen",
    row_id: str | int | None = None,
    details: str = "",
) -> bool:
    """
    Send an alert email when Google Flow session / persistent profile expires.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    row_info = f" (Sheet Row #{row_id})" if row_id else ""

    subject = f"\U0001f6a8 Action Required: Google Flow Session Expired{row_info}"

    text_body = f"""ALERT: Google Flow Session Expired

Your automated YouTube worker on AWS EC2 encountered an expired Google Flow session at {now_str}.
Channel: {channel}{row_info}

QUICK FIX (try this first — no laptop needed):
  SSH into EC2 and run:
    python /home/ubuntu/flow-worker/refresh_auth.py

  This refreshes the auth JSON from your existing persistent profile.
  Takes ~30 seconds. Then manually re-trigger the worker.

IF THE QUICK FIX FAILS (full profile expired — needs laptop):
1. Open a terminal on your laptop in:
   c:\\\\Desktop\\\\youtube Aauto\\\\watermark-pipeline

2. Run the profile creator:
   python create_profile.py

3. Log in to Google Flow in the browser window that opens.
   Navigate all the way inside the Flow Studio.
   Press Enter in the terminal when done.

4. The script will automatically upload the new persistent profile to EC2.
   Your next scheduled 9:00 AM IST daily run will succeed.

SESSION LONGEVITY:
  - Persistent profile (google_profile/): lasts MONTHS
  - refresh_auth.py crontab (every 3 days): extends JSON snapshot automatically
  - You should almost never need to run create_profile.py more than once per few months.

Technical Error Details:
{details or 'Session redirected to unauthenticated /about or login page.'}
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 24px; }}
    .card {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
    .header {{ background: #dc2626; color: #ffffff; padding: 20px 24px; }}
    .header h2 {{ margin: 0; font-size: 20px; font-weight: 700; }}
    .content {{ padding: 24px; }}
    .badge {{ display: inline-block; background: #fee2e2; color: #991b1b; padding: 4px 10px; border-radius: 9999px; font-size: 13px; font-weight: 600; margin-bottom: 16px; }}
    .quick-fix {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }}
    .quick-fix h4 {{ margin: 0 0 8px; color: #15803d; font-size: 14px; }}
    .steps {{ background: #f1f5f9; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }}
    .steps h4 {{ margin-top: 0; margin-bottom: 10px; color: #0f172a; }}
    .steps ol {{ margin: 0; padding-left: 20px; }}
    .steps li {{ margin-bottom: 10px; line-height: 1.5; }}
    code {{ background: #0f172a; color: #38bdf8; padding: 3px 8px; border-radius: 6px; font-family: Consolas, Monaco, monospace; font-size: 13px; }}
    .tip {{ font-size: 12px; color: #64748b; background: #f8fafc; border-left: 3px solid #cbd5e1; padding: 8px 12px; margin-top: 16px; border-radius: 0 4px 4px 0; }}
    .footer {{ font-size: 12px; color: #64748b; padding: 16px 24px; background: #f8fafc; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h2>\U0001f6a8 Action Required: Google Flow Session Expired</h2>
    </div>
    <div class="content">
      <div class="badge">AWS EC2 Worker Notice</div>
      <p>The automated video generator on your EC2 worker stopped because the Google Flow session expired.</p>

      <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
        <tr>
          <td style="padding: 6px 0; color: #64748b; font-size: 14px;"><strong>Channel:</strong></td>
          <td style="padding: 6px 0; font-size: 14px;"><code>{channel}</code></td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b; font-size: 14px;"><strong>Sheet Row:</strong></td>
          <td style="padding: 6px 0; font-size: 14px;">#{row_id if row_id else 'N/A'}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b; font-size: 14px;"><strong>Timestamp:</strong></td>
          <td style="padding: 6px 0; font-size: 14px;">{now_str}</td>
        </tr>
      </table>

      <div class="quick-fix">
        <h4>\u26a1 Quick Fix (no laptop needed — try this first):</h4>
        <p style="margin: 0 0 8px; font-size: 14px;">SSH into EC2 and run:</p>
        <code>python /home/ubuntu/flow-worker/refresh_auth.py</code>
        <p style="margin: 8px 0 0; font-size: 13px; color: #166534;">This refreshes the auth JSON from your existing persistent profile (~30 seconds).</p>
      </div>

      <div class="steps">
        <h4>If the quick fix fails (profile fully expired — needs laptop):</h4>
        <ol>
          <li>Open terminal in <code>c:\\\\Desktop\\\\youtube Aauto\\\\watermark-pipeline</code></li>
          <li>Run: <code>python create_profile.py</code></li>
          <li>Log in to Google Flow in the headed browser window that opens.</li>
          <li>Navigate <em>inside the Flow Studio</em>, then press <strong>Enter</strong> in the terminal.</li>
          <li>The script uploads everything to EC2 automatically.</li>
        </ol>
      </div>

      <div class="tip">
        <strong>Session longevity:</strong> The persistent profile (google_profile/) lasts months.
        The EC2 crontab runs <code>refresh_auth.py</code> every 3 days automatically to keep the
        JSON snapshot fresh. You should rarely need to run create_profile.py.
      </div>
    </div>
    <div class="footer">
      YouTube Auto Pipeline \u2022 AWS EC2 Worker Alert System
    </div>
  </div>
</body>
</html>
"""

    return send_email(
        subject=subject,
        text_content=text_body,
        html_content=html_body,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("--test", "test"):
        cfg = get_smtp_config()
        print("Checking SMTP Configuration:")
        print(f"  SMTP Host:      {cfg['host']}")
        print(f"  SMTP Port:      {cfg['port']}")
        print(f"  SMTP User:      {cfg['user'] or '(not configured)'}")
        print(f"  Recipient:      {cfg['recipient'] or '(not configured)'}")
        print(f"  Password Set:   {'Yes (' + '*' * 8 + ')' if cfg['password'] else 'No'}")

        if not is_email_configured():
            print("\n❌ Error: SMTP_USER, SMTP_PASSWORD, or NOTIFICATION_EMAIL_TO missing.")
            print("Please set them in your .env file or environment.")
            sys.exit(1)

        print("\nSending test email...")
        ok = send_email(
            subject="🧪 YouTube Auto Pipeline — Test Notification",
            text_content="This is a test notification from your YouTube Auto Pipeline email notifier.",
            html_content="<p>This is a <strong>test notification</strong> from your YouTube Auto Pipeline email notifier.</p>",
        )
        if ok:
            print("✅ Test email sent successfully!")
        else:
            print("❌ Failed to send test email. Check logs above.")
            sys.exit(1)
    else:
        print("Usage: python -m backend.services.email_notifier --test")
