"""
scripts/manual_login.py — Standalone script to handle Airtasker manual login.

Run this script ON YOUR HOST MACHINE (not in Docker) to log in manually.
It will save the session cookies to the shared volume that the agent uses.

Uses the same stealth + optional proxy settings as the agent, and prefers
**installed Google Chrome** (Playwright ``channel="chrome"``) so Cloudflare
Turnstile sees the same class of browser as when you open Chrome yourself.
Bundled Chromium alone often triggers error 600010.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Project root on path (loads .env via config.settings → stealth.browser)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from playwright.async_api import async_playwright

from stealth.browser import make_browser_context

SESSION_FILE = Path(".playwright_storage/airtasker_session.json")
LOGIN_URL = "https://www.airtasker.com/login/"
LOGGED_IN_SELECTORS = [
    "[data-testid='user-avatar']",
    "[data-testid='nav-profile']",
    "[aria-label='Profile menu']",
    "a[href='/dashboard/']",
]


async def run_manual_login() -> bool:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Starting manual login (preferring installed Google Chrome)…")

    async with async_playwright() as p:
        try:
            browser, context = await make_browser_context(
                p,
                storage_state=None,
                headless=False,
                channel="chrome",
                trust_browser_defaults=True,
                minimal_stealth=True,
            )
        except Exception as exc:
            logger.warning(
                f"Installed Chrome not available ({exc}); "
                "using bundled Chromium + synthetic fingerprint (Turnstile may fail)."
            )
            browser, context = await make_browser_context(
                p,
                storage_state=None,
                headless=False,
                channel=None,
                trust_browser_defaults=False,
                minimal_stealth=True,
            )

        page = await context.new_page()

        try:
            logger.info(f"Navigating to {LOGIN_URL}")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

            print("\n" + "=" * 60)
            print("  LOG IN IN THE WINDOW THAT OPENED.")
            print("  Same proxy as .env applies (if PROXY_HOST is set).")
            print("  When you reach the dashboard, this script saves the session.")
            print("=" * 60 + "\n")

            success = False
            while not success:
                if page.is_closed():
                    break
                for sel in LOGGED_IN_SELECTORS:
                    try:
                        if await page.locator(sel).first.is_visible(timeout=500):
                            success = True
                            break
                    except Exception:
                        continue
                if success:
                    break
                await asyncio.sleep(1)

            if success:
                logger.info("Login detected — saving storage state…")
                await context.storage_state(path=str(SESSION_FILE))
                logger.info(f"Session saved to {SESSION_FILE}")
                await asyncio.sleep(2)
                return True

            logger.error("Browser closed before login completed.")
            return False

        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        ok = asyncio.run(run_manual_login())
        raise SystemExit(0 if ok else 1)
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
        raise SystemExit(1)
