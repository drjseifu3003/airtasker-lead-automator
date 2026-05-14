"""
agent/session.py — Playwright session manager for Airtasker.

Responsibilities:
- Launch a stealth browser with proxy support.
- Login to Airtasker and persist session state to disk.
  Airtasker uses a TWO-STEP login: email first → Continue → password.
- Auto-detect session expiry and re-login.
- Run Cloudflare Turnstile solving (CapSolver + in-browser fallback) when challenges appear.
- Save a screenshot on any login failure for debugging.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import re

from loguru import logger
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from config.settings import settings
from agent.store import store, SessionStatus
from stealth.browser import make_browser_context
from stealth.captcha import solve_captcha_if_present

SESSION_DIR = Path(".playwright_storage")
SESSION_FILE = SESSION_DIR / "airtasker_session.json"
SCREENSHOT_DIR = Path("logs")

LOGIN_URL = "https://www.airtasker.com/login/"
CHECK_URL = "https://www.airtasker.com/dashboard/"

# Airtasker uses various selectors depending on A/B test variant
EMAIL_SELECTORS = [
    "input[name='email']",
    "input[name='username']",
    "input[type='email']",
    "input[placeholder*='email' i]",
    "input[autocomplete='email']",
]
PASSWORD_SELECTORS = [
    "input[name='password']",
    "input[type='password']",
    "input[id*='password' i]",
    "input[name*='password' i]",
    "input[placeholder*='password' i]",
    "input[autocomplete='current-password']",
    "input[autocomplete='password']",
    "input[aria-label*='password' i]",
]
SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "[role='button']:has-text('Continue')",
    "[data-testid='login-submit']",
]
PASSWORD_TOGGLE_SELECTORS = [
    "button:has-text('Use password')",
    "button:has-text('Use your password')",
    "button:has-text('Password instead')",
    "a:has-text('Use password')",
]
LOGGED_IN_SELECTORS = [
    "[data-testid='user-avatar']",
    "[data-testid='nav-profile']",
    "[aria-label='Profile menu']",
    "a[href='/dashboard/']",
    "a[href*='my-tasks']",
]


class SessionManager:
    """Manages a persistent, authenticated Playwright browser context."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        SESSION_DIR.mkdir(exist_ok=True)
        SCREENSHOT_DIR.mkdir(exist_ok=True)

    async def start(self) -> Page:
        """Start the browser and return a ready, authenticated page."""
        self._playwright = await async_playwright().start()
        self._browser, self._context = await make_browser_context(
            self._playwright,
            storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
        )
        self._page = await self._context.new_page()

        if SESSION_FILE.exists():
            if await self._is_logged_in():
                logger.info("[SESSION] Existing session valid ✓")
                await store.set_session_status(SessionStatus.VALID)
            else:
                logger.warning("[SESSION] Session file exists but is invalid/expired")
                await store.set_session_status(SessionStatus.EXPIRED)
        else:
            logger.info("[SESSION] No session file found")
            await store.set_session_status(SessionStatus.INVALID)

        return self._page

    async def manual_login(self) -> bool:
        """
        Launch a visible browser for manual login.
        Waits for the user to reach the dashboard.
        """
        await store.set_session_status(SessionStatus.LOGGING_IN)
        logger.info("[SESSION] Starting manual login (visible browser)...")

        try:
            pw = await async_playwright().start()
            try:
                # Prefer installed Google Chrome — Turnstile often fails on bundled Chromium.
                browser, context = await make_browser_context(
                    pw,
                    storage_state=None,
                    headless=False,
                    channel="chrome",
                    trust_browser_defaults=True,
                    minimal_stealth=True,
                )
            except Exception as e:
                logger.warning(
                    f"[SESSION] Chrome channel launch failed ({e}); "
                    "falling back to bundled Chromium (Turnstile may be harder)."
                )
                browser, context = await make_browser_context(
                    pw,
                    storage_state=None,
                    headless=False,
                    channel=None,
                    trust_browser_defaults=False,
                    minimal_stealth=True,
                )

            page = await context.new_page()

            await page.goto(LOGIN_URL)
            logger.info("[SESSION] Please log in manually in the opened browser window.")

            # Wait for successful login (indicator: reaching dashboard or profile avatar)
            # We'll poll for the LOGGED_IN_SELECTORS
            success = False
            for _ in range(300):  # 5 minute timeout
                if await page.is_closed():
                    break
                
                # Check for login indicators
                for sel in LOGGED_IN_SELECTORS:
                    try:
                        if await page.locator(sel).first.is_visible(timeout=500):
                            success = True
                            break
                    except:
                        continue
                
                if success:
                    break
                await asyncio.sleep(1)

            if success:
                logger.info("[SESSION] Login detected! Saving session...")
                await context.storage_state(path=str(SESSION_FILE))
                await store.set_session_status(SessionStatus.VALID)
                await asyncio.sleep(2) # Give it a moment
                return True
            else:
                logger.warning("[SESSION] Manual login timed out or browser closed.")
                await store.set_session_status(SessionStatus.INVALID)
                return False
        except Exception as exc:
            logger.error(f"[SESSION] Manual login error: {exc}")
            await store.add_log(f"[ERROR] Manual login failed: {exc}")
            await store.set_session_status(SessionStatus.INVALID)
            return False
        finally:
            if 'browser' in locals() and browser:
                await browser.close()
            if 'pw' in locals() and pw:
                await pw.stop()

    async def get_page(self) -> Page:
        """Return the active page, ensuring it's logged in."""
        if self._page is None or self._page.is_closed():
            return await self.start()
        
        # Check login status periodically
        if not await self._is_logged_in():
            logger.warning("[SESSION] Session expired")
            await store.set_session_status(SessionStatus.EXPIRED)
            # We don't automatically re-login anymore
        
        return self._page

    async def new_tab(self) -> Page:
        """Open a fresh tab in the existing context (for bidding)."""
        return await self._context.new_page()

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("[SESSION] Browser closed.")

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _screenshot(self, name: str) -> None:
        """Save a debug screenshot to logs/ for post-mortem analysis."""
        try:
            path = SCREENSHOT_DIR / f"{name}.png"
            await self._page.screenshot(path=str(path), full_page=True)
            logger.info(f"[SESSION] Screenshot saved → {path}")
        except Exception as exc:
            logger.warning(f"[SESSION] Could not save screenshot: {exc}")

    async def _is_login_error_page(self) -> bool:
        """Detect Airtasker's generic login error page (no form present)."""
        try:
            text = await self._page.inner_text("body", timeout=2_000)
        except Exception:
            return False

        lowered = text.lower()
        return (
            "sorry, something went wrong" in lowered
            or "an error occurred while logging you in" in lowered
        )

    async def _find_selector(self, selectors: list[str], timeout: int = 8_000) -> str | None:
        """Return the first selector whose element becomes visible before timeout."""
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            for sel in selectors:
                try:
                    locator = self._page.locator(sel).first
                    if await locator.is_visible(timeout=250):
                        logger.debug(f"[SESSION] Found selector: {sel}")
                        return sel
                except Exception:
                    continue
            await asyncio.sleep(0.2)
        return None

    async def _click_first_visible(
        self,
        selectors: list[str],
        timeout: int = 5_000,
    ) -> str | None:
        """Click the first visible selector and return it."""
        sel = await self._find_selector(selectors, timeout=timeout)
        if not sel:
            return None
        locator = self._page.locator(sel).first
        try:
            await locator.click(delay=80, timeout=2_500)
            return sel
        except Exception:
            try:
                await locator.click(force=True, timeout=2_500)
                return sel
            except Exception as exc:
                logger.warning(f"[SESSION] Click failed for selector {sel}: {exc}")
                return None

    async def _click_primary_continue(self, timeout: int = 8_000) -> bool:
        """Click the primary Airtasker Continue button (not social buttons)."""
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            try:
                button = self._page.locator("button").filter(has_text=re.compile(r"^Continue$", re.I)).first
                if await button.is_visible(timeout=250) and await button.is_enabled():
                    try:
                        await button.click(delay=80, timeout=2_500)
                        return True
                    except Exception:
                        await button.click(force=True, timeout=2_500)
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        return False

    async def _safe_click_selector(self, selector: str, timeout: int = 4_000) -> bool:
        """Attempt normal click then force-click for a selector, returning success."""
        locator = self._page.locator(selector).first
        try:
            await locator.click(delay=80, timeout=timeout)
            return True
        except Exception:
            try:
                await locator.click(force=True, timeout=timeout)
                return True
            except Exception as exc:
                logger.warning(f"[SESSION] Submit click failed for {selector}: {exc}")
                return False

    async def _submit_identifier_step(self) -> bool:
        """Submit the identifier (email) step using multiple non-skipping strategies."""
        try:
            clicked = await self._click_primary_continue(timeout=3_000)
            if clicked:
                return True
        except Exception:
            pass

        email_sel = await self._find_selector(EMAIL_SELECTORS, timeout=2_000)
        if email_sel:
            try:
                await self._page.locator(email_sel).first.press("Enter", timeout=2_000)
                return True
            except Exception:
                pass

        try:
            await self._page.evaluate(
                """() => {
                    const form = document.querySelector('form');
                    if (!form) return false;
                    form.requestSubmit();
                    return true;
                }"""
            )
            return True
        except Exception:
            return False

    async def _ensure_password_step(self, timeout: int = 15_000) -> str | None:
        """Ensure we are on the password step and return a matching password selector."""
        password_sel = await self._find_selector(PASSWORD_SELECTORS, timeout=4_000)
        if password_sel:
            return password_sel

        try:
            await self._page.wait_for_url("**/u/login/password**", timeout=timeout)
        except Exception:
            pass

        password_sel = await self._find_selector(PASSWORD_SELECTORS, timeout=4_000)
        if password_sel:
            return password_sel

        current_url = self._page.url
        if "/u/login/identifier" in current_url:
            logger.warning("[SESSION] Stuck on identifier step — re-submitting identifier form")
            submitted = await self._submit_identifier_step()
            if submitted:
                try:
                    await self._page.wait_for_url("**/u/login/password**", timeout=max(4_000, timeout))
                except Exception:
                    pass

        return await self._find_selector(PASSWORD_SELECTORS, timeout=6_000)

    async def _is_logged_in(self) -> bool:
        try:
            await self._page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=20_000)
            await solve_captcha_if_present(self._page)
            await asyncio.sleep(2)
            sel = await self._find_selector(LOGGED_IN_SELECTORS, timeout=5_000)
            return sel is not None
        except Exception:
            return False

    async def _login(self) -> None:
        """Legacy automated login — removed in favour of manual login."""
        pass


# Singleton
session = SessionManager()
