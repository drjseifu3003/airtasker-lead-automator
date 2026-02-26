"""
agent/session.py — Playwright session manager for Airtasker.

Responsibilities:
- Launch a stealth browser with proxy support.
- Login to Airtasker and persist session state to disk.
  Airtasker uses a TWO-STEP login: email first → Continue → password.
- Auto-detect session expiry and re-login.
- Wait for Cloudflare Turnstile to auto-solve in the real browser.
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
from stealth.browser import make_browser_context
from stealth.captcha import solve_captcha_if_present

SESSION_DIR = Path(".playwright_storage")
SESSION_FILE = SESSION_DIR / "airtasker_session.json"
SCREENSHOT_DIR = Path("logs")

HOMEPAGE_URL = "https://www.airtasker.com/"
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

# BrightData residential proxy takes ~25s per request.
# All timeouts must be >= 90s to avoid false failures.
_PAGE_LOAD_TIMEOUT  = 120_000   # 2 min  — full page load via proxy
_ELEMENT_TIMEOUT    = 90_000    # 90s    — wait for React to render
_NAV_TIMEOUT        = 120_000   # 2 min  — navigation/URL changes
_CHECK_TIMEOUT      = 60_000    # 60s    — session check


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

        if not await self._is_logged_in():
            logger.info("[SESSION] Not logged in — authenticating…")
            await self._login()
        else:
            logger.info("[SESSION] Existing session valid ✓")

        return self._page

    async def get_page(self) -> Page:
        """Return the active page, re-authenticating if needed."""
        if self._page is None:
            return await self.start()
        if not await self._is_logged_in():
            logger.warning("[SESSION] Session expired — re-logging in…")
            await self._login()
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
                    if await locator.is_visible(timeout=500):
                        logger.debug(f"[SESSION] Found selector: {sel}")
                        return sel
                except Exception:
                    continue
            await asyncio.sleep(0.3)
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
                if await button.is_visible(timeout=500) and await button.is_enabled():
                    try:
                        await button.click(delay=80, timeout=2_500)
                        return True
                    except Exception:
                        await button.click(force=True, timeout=2_500)
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.3)
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
        """Submit the identifier (email) step using multiple strategies."""
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
            await self._page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=_CHECK_TIMEOUT)
            await asyncio.sleep(3)
            sel = await self._find_selector(LOGGED_IN_SELECTORS, timeout=10_000)
            return sel is not None
        except Exception:
            return False

    async def _login(self) -> None:
        from stealth.behavior import human_type, random_sleep

        page = self._page
        logger.info(f"[SESSION] Navigating to {LOGIN_URL}")

        # Step 1: Load the Airtasker homepage (not the login modal directly).
        # The login page is a Next.js SPA — navigating to /login/ loads the
        # homepage shell first, then opens a modal. Via proxy this modal may
        # not render. Instead we: load homepage → click "Log in" → wait for
        # Auth0 redirect which gives us a fresh state parameter.
        # The Airtasker "Log in" button has href="#" but onclick triggers a JS
        # redirect to id.airtasker.com with a fresh ?state= parameter.
        # Strategy: load homepage → find the Log in anchor by text → JS click it
        # (bypasses any href="#" interception) → wait for Auth0 URL.
        logger.info("[SESSION] Loading Airtasker homepage…")
        await page.goto(HOMEPAGE_URL, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT)
        await random_sleep(4, 6)
        await self._screenshot("login_01_page_loaded")
        logger.info(f"[SESSION] Landed on: {page.url}")

        # Use JS click to ensure the onclick handler fires (not just href navigation)
        logger.info("[SESSION] JS-clicking Log in button…")
        clicked = False
        try:
            # Find the Log in link by exact text and dispatch a real click event
            clicked = await page.evaluate("""() => {
                // Find all anchors/buttons with 'Log in' text
                const els = [...document.querySelectorAll('a, button')];
                const btn = els.find(el => el.textContent.trim() === 'Log in');
                if (btn) {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    return true;
                }
                return false;
            }""")
        except Exception as e:
            logger.warning(f"[SESSION] JS click failed: {e}")

        if clicked:
            logger.info("[SESSION] JS click fired — waiting for Auth0 redirect…")
        else:
            # Fallback: Playwright click
            logger.info("[SESSION] JS click failed — trying Playwright click…")
            try:
                await page.locator("a:has-text('Log in'), button:has-text('Log in')").first.click(timeout=10_000)
                clicked = True
            except Exception as e:
                logger.warning(f"[SESSION] Playwright click also failed: {e}")

        if clicked:
            try:
                await page.wait_for_url("**/u/login/**", timeout=_PAGE_LOAD_TIMEOUT)
                logger.info(f"[SESSION] Auth0 redirect successful: {page.url}")
            except Exception:
                logger.warning(f"[SESSION] No Auth0 redirect after click (url={page.url})")

        # If we're still not on Auth0, navigate directly to /login/ as last resort
        if "id.airtasker.com" not in page.url:
            logger.info("[SESSION] Navigating directly to /login/ as fallback…")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT)
            await random_sleep(2, 3)
            # One more attempt to click Log in if we got the homepage again
            if "id.airtasker.com" not in page.url:
                try:
                    await page.evaluate("""() => {
                        const els = [...document.querySelectorAll('a, button')];
                        const btn = els.find(el => el.textContent.trim() === 'Log in');
                        if (btn) { btn.click(); return true; }
                        return false;
                    }""")
                    await page.wait_for_url("**/u/login/**", timeout=_PAGE_LOAD_TIMEOUT)
                    logger.info(f"[SESSION] Auth0 redirect on retry: {page.url}")
                except Exception:
                    pass

        await random_sleep(2, 3)
        await self._screenshot("login_01b_on_auth0")
        logger.info(f"[SESSION] Current URL before email: {page.url}")

        # ── Step 2: Enter email ────────────────────────────────────────────────
        # Long timeout — proxy is slow and React may take time to hydrate
        email_sel = await self._find_selector(EMAIL_SELECTORS, timeout=_ELEMENT_TIMEOUT)
        if not email_sel:
            await self._screenshot("login_error_no_email_field")
            raise RuntimeError(
                "[SESSION] Could not find email input on Airtasker login page. "
                "Check logs/login_error_no_email_field.png for a screenshot."
            )

        logger.info(f"[SESSION] Typing email into: {email_sel}")
        await human_type(page, email_sel, settings.airtasker_email)
        await random_sleep(0.5, 1.0)

        # Wait for Airtasker's "Verifying..." spinner to disappear
        logger.info("[SESSION] Waiting for Airtasker email verification to complete…")
        try:
            await page.wait_for_function(
                "!document.body.innerText.includes('Verifying')",
                timeout=15_000,
            )
        except Exception:
            pass
        await asyncio.sleep(2.5)
        await self._screenshot("login_01b_after_email_verified")

        # Log frames for debugging
        for i, frame in enumerate(page.frames):
            logger.debug(f"[SESSION] Frame[{i}]: url={frame.url} name={frame.name}")

        # ── Step 2: Wait for Turnstile to auto-solve in THIS browser ──────────
        logger.info("[SESSION] Waiting for Turnstile to solve in browser…")
        turnstile_solved = await solve_captcha_if_present(page)
        if turnstile_solved:
            logger.info("[SESSION] Turnstile solved ✓")
            await random_sleep(0.5, 1.0)
            await self._screenshot("login_01c_after_checkbox_checked")
        else:
            logger.warning(
                "[SESSION] Turnstile did not auto-solve. Browser may be flagged as bot. "
                "Add a residential proxy (PROXY_SERVER in .env) to fix this."
            )

        # ── Step 3: Click Continue ─────────────────────────────────────────────
        clicked_primary_continue = await self._click_primary_continue(timeout=8_000)
        if clicked_primary_continue:
            logger.info("[SESSION] Clicking primary Continue button")
            await random_sleep(2, 3)
        else:
            continue_sel = await self._click_first_visible(SUBMIT_SELECTORS, timeout=5_000)
            if continue_sel:
                logger.info(f"[SESSION] Clicking fallback submit button: {continue_sel}")
                await random_sleep(2, 3)
            else:
                logger.info("[SESSION] No Continue button found — pressing Enter")
                await page.keyboard.press("Enter")
                await random_sleep(2, 3)

        await self._screenshot("login_02_after_continue")

        # ── Step 4: Navigate to password step ─────────────────────────────────
        # After Continue, Auth0 does a server round-trip — allow extra time via proxy
        password_sel = await self._ensure_password_step(timeout=_NAV_TIMEOUT)
        if not password_sel:
            logger.warning("[SESSION] Password field not visible after first continue — retrying once")
            await self._click_primary_continue(timeout=4_000)
            await random_sleep(1.5, 2.5)

        await solve_captcha_if_present(page)

        password_toggle_sel = await self._click_first_visible(PASSWORD_TOGGLE_SELECTORS, timeout=3_000)
        if password_toggle_sel:
            logger.info(f"[SESSION] Opened password login via: {password_toggle_sel}")
            await random_sleep(2, 3)

        # ── Step 5: Enter password ─────────────────────────────────────────────
        password_sel = password_sel or await self._ensure_password_step(timeout=_NAV_TIMEOUT)
        if not password_sel:
            await self._screenshot("login_error_no_password_field")
            is_error_page = await self._is_login_error_page()
            if is_error_page:
                raise RuntimeError(
                    "[SESSION] Airtasker showed a login error page. "
                    "Verify credentials manually and check logs/login_error_no_password_field.png."
                )
            logger.error(f"[SESSION] Password field not found. Current URL: {page.url}")
            raise RuntimeError(
                "[SESSION] Could not find password input. "
                "Check logs/login_error_no_password_field.png"
            )

        logger.info(f"[SESSION] Typing password into: {password_sel}")
        await human_type(page, password_sel, settings.airtasker_password)
        await random_sleep(0.5, 1.2)

        # ── Step 6: Submit ─────────────────────────────────────────────────────
        submit_sel = await self._find_selector(SUBMIT_SELECTORS, timeout=5_000)
        if submit_sel:
            logger.info(f"[SESSION] Submitting via: {submit_sel}")
            clicked = await self._safe_click_selector(submit_sel, timeout=4_000)
            if not clicked:
                await page.keyboard.press("Enter")
        else:
            await page.keyboard.press("Enter")

        await random_sleep(3, 5)
        await solve_captcha_if_present(page)
        await self._screenshot("login_03_post_submit")

        # ── Step 7: Confirm login ──────────────────────────────────────────────
        logged_in_sel = await self._find_selector(LOGGED_IN_SELECTORS, timeout=_ELEMENT_TIMEOUT)
        if not logged_in_sel:
            await self._screenshot("login_error_failed")
            logger.error(f"[SESSION] Login failed. Current URL: {page.url}")
            raise RuntimeError(
                "[SESSION] Airtasker login failed — check credentials, CAPTCHA, or "
                "inspect logs/login_error_failed.png"
            )

        logger.info("[SESSION] Login successful ✓")
        await self._context.storage_state(path=str(SESSION_FILE))
        logger.info(f"[SESSION] Session saved to {SESSION_FILE}")
        await random_sleep(1, 2)


# Singleton
session = SessionManager()