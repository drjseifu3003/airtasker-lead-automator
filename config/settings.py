"""
AI Lead Automation — Settings
Loads all configuration from environment variables / .env file.
"""

from __future__ import annotations

import json
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI / LLM (supports OpenAI, Groq, OpenRouter, etc.) ─────────────────
    openai_api_key: str = Field(..., description="API key for the LLM provider")
    openai_model: str = Field("gpt-4o-mini", description="Model name (e.g. llama-3.1-8b-instant for Groq)")
    openai_base_url: str = Field("", description="Optional: override base URL for Groq/OpenRouter")

    # ── Airtasker ─────────────────────────────────────────────────────────────
    airtasker_email: str = Field(..., description="Airtasker login email")
    airtasker_password: str = Field(..., description="Airtasker login password")

    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    telegram_chat_id: str = Field(..., description="Telegram chat ID to send alerts to")

    # ── 2Captcha ──────────────────────────────────────────────────────────────
    twocaptcha_api_key: str = Field("", description="2Captcha API key")

    # ── Proxy ─────────────────────────────────────────────────────────────────
    proxy_host: str = Field("", description="Residential proxy host")
    proxy_port: int = Field(8080, description="Residential proxy port")
    proxy_username: str = Field("", description="Proxy username")
    proxy_password: str = Field("", description="Proxy password")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard_port: int = Field(8000, description="Dashboard HTTP port")
    dashboard_secret: str = Field("changeme", description="Basic auth secret for dashboard")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field("redis://localhost:6379/0", description="Redis URL for dedup state")

    # ── Agent Behaviour ───────────────────────────────────────────────────────
    dry_run: bool = Field(False, description="If True, evaluate but never bid")
    log_level: str = Field("INFO", description="Logging level")

    @property
    def proxy_server(self) -> str | None:
        """Return formatted proxy server string for Playwright, or None if not set."""
        if self.proxy_host:
            return f"http://{self.proxy_host}:{self.proxy_port}"
        return None

    @property
    def proxy_config(self) -> dict | None:
        """Return Playwright proxy config dict, or None if proxy not configured."""
        if not self.proxy_host:
            return None
        cfg = {"server": self.proxy_server}
        if self.proxy_username:
            cfg["username"] = self.proxy_username
            cfg["password"] = self.proxy_password
        return cfg


def load_profile(profile_path: str = "config/profiles/default.json") -> dict:
    """Load a carpenter profile from JSON."""
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")
    return json.loads(path.read_text(encoding="utf-8"))


# Singleton — import and use anywhere
settings = Settings()
