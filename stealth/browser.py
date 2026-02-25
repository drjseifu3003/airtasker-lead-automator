"""
stealth/browser.py — Stealth Playwright browser factory.

Launches a Chromium instance with:
- playwright-stealth patches (spoofs navigator, plugins, WebGL, etc.)
- Randomised User-Agent, viewport, locale, timezone
- Optional residential proxy
- Canvas/WebGL fingerprint noise injection
"""
from __future__ import annotations

import random
from typing import Optional

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Playwright
from playwright_stealth import stealth_async

from config.settings import settings

# Pool of realistic User-Agents
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

_TIMEZONES = [
    "Australia/Sydney",
    "Australia/Melbourne",
    "Australia/Brisbane",
]

# Minimal JS to add noise to Canvas and WebGL fingerprints
_FINGERPRINT_NOISE_SCRIPT = """
(function() {
    const noise = () => Math.random() * 0.001;

    // Canvas noise
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {
        const data = origGetImageData.apply(this, args);
        for (let i = 0; i < data.data.length; i += 4) {
            data.data[i]   = Math.min(255, data.data[i]   + Math.round(noise() * 10));
            data.data[i+1] = Math.min(255, data.data[i+1] + Math.round(noise() * 10));
            data.data[i+2] = Math.min(255, data.data[i+2] + Math.round(noise() * 10));
        }
        return data;
    };

    // WebGL noise on getParameter
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        const val = origGetParam.call(this, param);
        if (param === 37445) return 'Intel Inc.';   // VENDOR
        if (param === 37446) return 'Intel Iris OpenGL Engine';  // RENDERER
        return val;
    };
})();
"""


async def make_browser_context(
    playwright: Playwright,
    storage_state: Optional[str] = None,
) -> tuple[Browser, BrowserContext]:
    """
    Launch a stealth-patched Chromium browser and create an authenticated context.
    Returns (browser, context).
    """
    ua = random.choice(_USER_AGENTS)
    viewport = random.choice(_VIEWPORTS)
    timezone = random.choice(_TIMEZONES)
    locale = "en-AU"

    logger.debug(f"[BROWSER] UA={ua[:40]}... viewport={viewport} tz={timezone}")

    launch_kwargs: dict = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }

    proxy_cfg = settings.proxy_config
    if proxy_cfg:
        launch_kwargs["proxy"] = proxy_cfg
        logger.info(f"[BROWSER] Proxy enabled: {proxy_cfg['server']}")
    else:
        logger.warning("[BROWSER] No proxy configured — detection risk elevated")

    browser = await playwright.chromium.launch(**launch_kwargs)

    context_kwargs: dict = {
        "user_agent": ua,
        "viewport": viewport,
        "locale": locale,
        "timezone_id": timezone,
        "java_script_enabled": True,
        "bypass_csp": True,
        "extra_http_headers": {
            "Accept-Language": "en-AU,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
    }

    if storage_state:
        context_kwargs["storage_state"] = storage_state
        logger.info(f"[BROWSER] Loading stored session: {storage_state}")

    context = await browser.new_context(**context_kwargs)

    # Inject fingerprint noise into every page
    await context.add_init_script(_FINGERPRINT_NOISE_SCRIPT)

    # Apply playwright-stealth to every new page
    context.on("page", lambda page: _apply_stealth(page))  # type: ignore

    return browser, context


def _apply_stealth(page) -> None:
    """Schedule stealth patches on a newly opened page."""
    import asyncio
    asyncio.ensure_future(stealth_async(page))
