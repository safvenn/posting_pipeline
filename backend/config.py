"""Application configuration via pydantic-settings."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://user:pass@localhost:5432/watermark_pipeline"

    # Google OAuth (used for ALL YouTube channels)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Legacy per-channel YouTube fallback (optional)
    yt_client_id_channel_a: str = ""
    yt_client_secret_channel_a: str = ""
    yt_refresh_token_channel_a: str = ""
    yt_client_id_channel_b: str = ""
    yt_client_secret_channel_b: str = ""
    yt_refresh_token_channel_b: str = ""

    def get_google_oauth_credentials(self) -> tuple[str, str]:
        """Return (client_id, client_secret) for Google OAuth."""
        cid = self.google_client_id or self.yt_client_id_channel_b or self.yt_client_id_channel_a
        csec = self.google_client_secret or self.yt_client_secret_channel_b or self.yt_client_secret_channel_a
        return cid, csec

    # File storage
    upload_dir: str = "./uploads"
    processed_dir: str = "./processed"
    log_dir: str = "./logs"

    # Timezone — always IST, never change
    timezone: str = "Asia/Kolkata"

    # SSH Worker (runs gwr — Gemini Watermark Remover)
    worker_ssh_host: str = ""
    worker_ssh_port: int = 22
    worker_ssh_user: str = "ubuntu"
    worker_ssh_key_path: str = "~/.ssh/id_rsa"
    worker_ssh_key_content: str = ""
    worker_ssh_password: str = ""
    gwr_worker_dir: str = "/home/ubuntu/video-worker"
    gwr_tmp_dir: str = "/home/ubuntu/video-worker/tmp"
    gwr_video_bitrate_mbps: int = 30

    # Gemini API (Google AI Studio)
    gemini_api_key: str = ""
    # Valid public API model names (override via GEMINI_MODEL env var on Render):
    #   gemini-2.0-flash        — fastest, cheapest (default)
    #   gemini-1.5-flash        — good balance
    #   gemini-1.5-pro          — highest quality, slower
    # INVALID (does not exist): models/gemini-3.5-flash-lite
    gemini_model: str = "gemini-2.0-flash"

    # Google Sheets (service account JSON)
    google_sheets_service_account_json: str = "./service_account.json"
    google_sheets_id_channel_a: str = "15di4I6FImBRN0EqXpC1azZT1BVIeTEYjRFiaMPsZOPw"
    google_sheets_tab_channel_a: str = "indian_food_miniature_asmr_prompts"
    google_sheets_id_channel_b: str = "1I55wxInth8l7UFWmTd5K0cBauhGO1AsM5q_bspQpvAI"
    google_sheets_tab_channel_b: str = "30_fruit_growth_video_prompts"

    # Channel SEO tag pools (semicolon-separated)
    seo_tags_channel_a: str = "cooking;recipe;food;homemade;easyrecipe;quickmeals;delicious;foodie"
    seo_tags_channel_b: str = "asmr;satisfying;relaxing;sounds;tapping;crunchy;asmrvideo;sleep"

    # Optional LLM
    anthropic_api_key: Optional[str] = None

    # Telegram notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Backend public URL (Render / custom domain / tunnel for serving media to Instagram Graph API)
    backend_public_url: str = os.getenv("RENDER_EXTERNAL_URL", os.getenv("BACKEND_PUBLIC_URL", ""))

    # CORS — comma-separated list of allowed frontend origins
    # Example: http://localhost:5173,https://mypipeline.vercel.app
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    # API key for bearer-token auth on all /api/* routes (except /api/health)
    # Generate a strong random value and set in .env: API_KEY=<random-64-char-hex>
    api_key: str = ""

    # ASMR Content Workflow
    asmr_dry_run: bool = False
    asmr_schedule_cron: str = "0 9 * * *"
    asmr_food_sheet_id: str = "1XmQIPm4VtvAciiMo43T-BjyQsPCiI82AU-_tFyjGKVo"
    asmr_food_sheet_tab: str = "Sheet1"

    def upload_path(self) -> Path:
        if Path("/var/data").exists() and Path("/var/data").is_dir():
            p = (Path("/var/data") / "uploads").resolve()
        else:
            p = Path(self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def processed_path(self) -> Path:
        if Path("/var/data").exists() and Path("/var/data").is_dir():
            p = (Path("/var/data") / "processed").resolve()
        else:
            p = Path(self.processed_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def log_path(self) -> Path:
        if Path("/var/data").exists() and Path("/var/data").is_dir():
            p = (Path("/var/data") / "logs").resolve()
        else:
            p = Path(self.log_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def seo_tags_for(self, channel: str) -> list[str]:
        raw = self.seo_tags_channel_a if channel == "channel_a" else self.seo_tags_channel_b
        return [t.strip() for t in raw.split(";") if t.strip()]


settings = Settings()
