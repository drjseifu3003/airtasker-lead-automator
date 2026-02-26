"""
stealth/captcha.py

KEY INSIGHT: 2Captcha tokens are bound to 2Captcha's browser fingerprint.
Auth0 + Cloudflare verify that the token came from the SAME browser/IP that
is submitting the form. Injecting a foreign token ALWAYS fails silently.

Correct approach: wait for Turnstile to auto-solve in OUR browser.
Turnstile 'flexible' mode often passes automatically when the browser
looks sufficiently human. We just need to wait for it.
"""
from __future__ import annotations

import asyncio

from loguru import logger
from playwright.async_api import Page


async def solve_captcha_if_present(page: Page) -> bool:
    """
    Wait for Cloudflare Turnstile to auto-solve in the current browser.
    Returns True if solved or no captcha present, False if timed out.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        await asyncio.sleep(1.0)
    except Exception:
        pass

    # Check if Turnstile iframe is present
    if not any("challenges.cloudflare.com" in f.url for f in page.frames):
        return True  # No captcha

    logger.info("[CAPTCHA] Turnstile detected — waiting for browser auto-solve…")

    # Wait up to 30s for auto-solve
    if await _wait_for_token(page, timeout_secs=30):
        logger.info("[CAPTCHA] Turnstile auto-solved ✓")
        return True

    # Try clicking the checkbox manually then wait again
    logger.info("[CAPTCHA] Not auto-solved — trying checkbox click…")
    await _click_checkbox(page)
    if await _wait_for_token(page, timeout_secs=15):
        logger.info("[CAPTCHA] Turnstile solved after click ✓")
        return True

    logger.warning("[CAPTCHA] Turnstile unsolved — browser likely flagged as bot. "
                   "Consider adding a residential proxy.")
    return False


async def _wait_for_token(page: Page, timeout_secs: int) -> bool:
    """Poll until cf-turnstile-response has a value or iframe shows success."""
    for _ in range(timeout_secs * 2):
        await asyncio.sleep(0.5)
        try:
            token = await page.evaluate(
                "() => (document.querySelector('input[name=\"cf-turnstile-response\"]') || {}).value || ''"
            )
            if token and len(token) > 20:
                logger.debug(f"[CAPTCHA] Token found in DOM ({len(token)} chars)")
                return True
        except Exception:
            pass

        # Also check iframe success state
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            try:
                done = await frame.evaluate("""() => {
                    const cb = document.querySelector('input[type="checkbox"]');
                    return cb ? cb.checked : false;
                }""")
                if done:
                    return True
            except Exception:
                pass
    return False


async def _click_checkbox(page: Page) -> None:
    """Click the Turnstile checkbox using absolute page coordinates."""
    try:
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            iframe_el = await frame.frame_element()
            iframe_box = await iframe_el.bounding_box()
            if not iframe_box:
                continue
            try:
                cb = frame.locator("input[type='checkbox'], [role='checkbox']").first
                cb_box = await cb.bounding_box(timeout=2_000)
                if cb_box:
                    await page.mouse.click(
                        iframe_box["x"] + cb_box["x"] + cb_box["width"] / 2,
                        iframe_box["y"] + cb_box["y"] + cb_box["height"] / 2,
                    )
                    logger.debug("[CAPTCHA] Clicked checkbox")
                    return
            except Exception:
                pass
            # Fallback: click left side of iframe where checkbox usually is
            await page.mouse.click(
                iframe_box["x"] + 24,
                iframe_box["y"] + iframe_box["height"] / 2,
            )
            logger.debug("[CAPTCHA] Clicked iframe (fallback)")
            return
    except Exception as exc:
        logger.debug(f"[CAPTCHA] Click failed: {exc}")