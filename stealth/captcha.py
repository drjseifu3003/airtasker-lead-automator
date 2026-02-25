"""
stealth/captcha.py — 2Captcha solver integration for Playwright pages.

Detects Cloudflare Turnstile, hCaptcha, and reCAPTCHA v2/v3 on the
current page, solves them via the 2Captcha API, and injects the
solution token so the form can proceed normally.
"""
from __future__ import annotations

import asyncio

from loguru import logger
from playwright.async_api import Page
from twocaptcha import TwoCaptcha

from config.settings import settings

_solver: TwoCaptcha | None = None


def _get_solver() -> TwoCaptcha:
    global _solver
    if _solver is None:
        if not settings.twocaptcha_api_key:
            raise RuntimeError("TWOCAPTCHA_API_KEY is not configured")
        _solver = TwoCaptcha(settings.twocaptcha_api_key)
    return _solver


async def solve_captcha_if_present(page: Page) -> bool:
    """
    Detect and solve any CAPTCHA on the page.
    Returns True if a CAPTCHA was detected and solved, False otherwise.
    Safe to call at any point — it waits for page stability first and
    silently returns False if the page navigates mid-check.
    """
    try:
        # Wait for any pending navigation to settle before querying the DOM
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        await asyncio.sleep(1.5)  # let anti-bot JS initialise
    except Exception:
        # Page may already be stable or navigating — continue anyway
        await asyncio.sleep(1)

    # ── Cloudflare Turnstile ──────────────────────────────────────────────────
    try:
        turnstile_el = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
        if turnstile_el:
            logger.info("[CAPTCHA] Cloudflare Turnstile detected — solving via 2Captcha…")
            site_key = await _extract_turnstile_sitekey(page)
            if site_key:
                return await _solve_turnstile(page, site_key)
    except Exception as exc:
        logger.debug(f"[CAPTCHA] Turnstile check skipped (navigation?): {exc}")

    # ── hCaptcha ──────────────────────────────────────────────────────────────
    try:
        hcaptcha_el = await page.query_selector("iframe[src*='hcaptcha.com']")
        if hcaptcha_el:
            logger.info("[CAPTCHA] hCaptcha detected — solving via 2Captcha…")
            site_key = await _extract_hcaptcha_sitekey(page)
            if site_key:
                return await _solve_hcaptcha(page, site_key)
    except Exception as exc:
        logger.debug(f"[CAPTCHA] hCaptcha check skipped (navigation?): {exc}")

    # ── reCAPTCHA v2 ─────────────────────────────────────────────────────────
    try:
        recaptcha_el = await page.query_selector(".g-recaptcha, iframe[src*='recaptcha']")
        if recaptcha_el:
            logger.info("[CAPTCHA] reCAPTCHA v2 detected — solving via 2Captcha…")
            site_key = await _extract_recaptcha_sitekey(page)
            if site_key:
                return await _solve_recaptcha(page, site_key)
    except Exception as exc:
        logger.debug(f"[CAPTCHA] reCAPTCHA check skipped (navigation?): {exc}")

    return False


# ── Solvers ───────────────────────────────────────────────────────────────────

async def _solve_turnstile(page: Page, site_key: str) -> bool:
    url = page.url
    try:
        result = await asyncio.to_thread(
            _get_solver().turnstile,
            sitekey=site_key,
            url=url,
        )
        token = result["code"]
        await _inject_turnstile_token(page, token)
        logger.info("[CAPTCHA] Turnstile solved ✓")
        return True
    except Exception as exc:
        logger.error(f"[CAPTCHA] Turnstile solve failed: {exc}")
        return False


async def _solve_hcaptcha(page: Page, site_key: str) -> bool:
    url = page.url
    try:
        result = await asyncio.to_thread(
            _get_solver().hcaptcha,
            sitekey=site_key,
            url=url,
        )
        token = result["code"]
        await page.evaluate(
            f"document.querySelector('[name=\"h-captcha-response\"]').value = '{token}';"
        )
        logger.info("[CAPTCHA] hCaptcha solved ✓")
        return True
    except Exception as exc:
        logger.error(f"[CAPTCHA] hCaptcha solve failed: {exc}")
        return False


async def _solve_recaptcha(page: Page, site_key: str) -> bool:
    url = page.url
    try:
        result = await asyncio.to_thread(
            _get_solver().recaptcha,
            sitekey=site_key,
            url=url,
        )
        token = result["code"]
        await page.evaluate(
            f"document.getElementById('g-recaptcha-response').innerHTML = '{token}';"
        )
        logger.info("[CAPTCHA] reCAPTCHA solved ✓")
        return True
    except Exception as exc:
        logger.error(f"[CAPTCHA] reCAPTCHA solve failed: {exc}")
        return False


# ── Site key extraction ───────────────────────────────────────────────────────

async def _extract_turnstile_sitekey(page: Page) -> str | None:
    return await page.evaluate("""
        (() => {
            const el = document.querySelector('[data-sitekey]');
            if (el) return el.getAttribute('data-sitekey');
            const m = document.body.innerHTML.match(/sitekey['":\\s]+([A-Za-z0-9_-]{20,})/);
            return m ? m[1] : null;
        })()
    """)


async def _extract_hcaptcha_sitekey(page: Page) -> str | None:
    return await page.evaluate("""
        (() => {
            const el = document.querySelector('[data-hcaptcha-sitekey], .h-captcha[data-sitekey]');
            return el ? el.getAttribute('data-sitekey') : null;
        })()
    """)


async def _extract_recaptcha_sitekey(page: Page) -> str | None:
    return await page.evaluate("""
        (() => {
            const el = document.querySelector('.g-recaptcha[data-sitekey]');
            return el ? el.getAttribute('data-sitekey') : null;
        })()
    """)


async def _inject_turnstile_token(page: Page, token: str) -> None:
    await page.evaluate(f"""
        (() => {{
            const input = document.querySelector('[name="cf-turnstile-response"]');
            if (input) input.value = '{token}';
            if (window.turnstile) window.turnstile.reset();
        }})()
    """)
