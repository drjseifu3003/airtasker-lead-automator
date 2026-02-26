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

    # ── OpenAI / LLM ──────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="API key for the LLM provider")
    openai_model: str = Field("gpt-4o-mini", description="Model name")
    openai_base_url: str = Field("", description="Optional: override base URL for Groq/OpenRouter")

    # ── Airtasker ─────────────────────────────────────────────────────────────
    airtasker_email: str = Field(..., description="Airtasker login email")
    airtasker_password: str = Field(..., description="Airtasker login password")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    telegram_chat_id: str = Field(..., description="Telegram chat ID to send alerts to")

    # ── 2Captcha ──────────────────────────────────────────────────────────────
    twocaptcha_api_key: str = Field("", description="2Captcha API key")

    # ── Proxy ─────────────────────────────────────────────────────────────────
    # Use empty string defaults so we can detect "not configured"
    proxy_host: str = Field("", description="Proxy host (leave empty to disable)")
    proxy_port: int = Field(1081, description="Proxy port")
    proxy_username: str = Field("", description="Proxy username")
    proxy_password: str = Field("", description="Proxy password")
    # Proxy protocol: use 'socks5' for proxybase.org and most residential proxies
    # Use 'http' only for HTTP CONNECT proxies
    proxy_protocol: str = Field("socks5", description="Proxy protocol: socks5 or http")

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
        """Return formatted proxy URL for Playwright, or None if not configured."""
        if not self.proxy_host:
            return None
        return f"{self.proxy_protocol}://{self.proxy_username}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"

    @property
    def proxy_config(self) -> dict | None:
        """Return Playwright proxy config dict, or None if proxy not configured."""
        server = self.proxy_server
        if not server:
            return None
        return {
            "server": server,
            "username": self.proxy_username,
            "password": self.proxy_password,
        }


def load_profile(profile_path: str = "config/profiles/default.json") -> dict:
    """Load a carpenter profile from JSON."""
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")
    return json.loads(path.read_text(encoding="utf-8"))


# Singleton — import and use anywhere
settings = Settings()