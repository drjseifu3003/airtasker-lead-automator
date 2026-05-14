"""
stealth/captcha.py — Cloudflare Turnstile handling for Playwright.

1. If CAPSOLVER_API_KEY is set, extract the sitekey from the page, request a token
   from CapSolver (AntiTurnstileTaskProxyLess), inject it, then verify.
   See: https://docs.capsolver.com/guide/captcha/cloudflare_turnstile/

2. Otherwise (or if CapSolver fails), wait for in-browser auto-solve / checkbox
   interaction (best-effort fallback).

Note: Some stacks bind Turnstile tokens to TLS/session; CapSolver + same-browser
injection works for many sites including typical Auth0/Airtasker flows, but is
not guaranteed if the origin adds extra checks.
"""
from __future__ import annotations

import asyncio

from loguru import logger
from playwright.async_api import Page

from config.settings import settings
from stealth.capsolver_client import CapSolverError, solve_turnstile_token


_TURNSTILE_SITEKEY_JS = r"""
() => {
  const fromAttr = document.querySelector('[data-sitekey]');
  if (fromAttr) {
    const k = fromAttr.getAttribute('data-sitekey');
    if (k && k.length > 10) return k;
  }
  for (const f of document.querySelectorAll('iframe')) {
    const src = f.getAttribute('src') || '';
    if (!src.includes('challenges.cloudflare.com') && !src.includes('turnstile')) continue;
    try {
      const abs = new URL(src, location.href);
      const k = abs.searchParams.get('k');
      if (k && k.startsWith('0x')) return k;
    } catch (e) {}
    const m = src.match(/[?&]k=(0x[0-9A-Za-z_-]+)/);
    if (m) return m[1];
  }
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const m2 = html.match(/0x4AAAA[A-Za-z0-9_-]{10,}/);
  if (m2) return m2[0];
  return null;
}
"""

_TURNSTILE_META_JS = r"""
() => {
  const el = document.querySelector('.cf-turnstile[data-action], [data-sitekey][data-action]');
  const action = el && el.getAttribute('data-action') ? el.getAttribute('data-action') : null;
  const cdataEl = document.querySelector('[data-cdata]');
  const cdata = cdataEl && cdataEl.getAttribute('data-cdata') ? cdataEl.getAttribute('data-cdata') : null;
  return { action: action || null, cdata: cdata || null };
}
"""

_INJECT_TOKEN_JS = r"""
(token) => {
  const selectors = [
    'textarea[name="cf-turnstile-response"]',
    'input[name="cf-turnstile-response"]',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')
      || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (proto && proto.set) proto.set.call(el, token);
    else el.value = token;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  return true;
}
"""


def _capsolver_configured() -> bool:
    return bool((settings.capsolver_api_key or "").strip())


async def solve_captcha_if_present(page: Page) -> bool:
    """
    Resolve Cloudflare Turnstile if present on the current page.

    Returns True if no challenge, solved successfully, or token already present.
    Returns False if solving failed after all strategies.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        await asyncio.sleep(0.5)
    except Exception:
        pass

    has_turnstile = any(
        "challenges.cloudflare.com" in f.url or "turnstile" in f.url.lower()
        for f in page.frames
    )
    if not has_turnstile:
        return True

    if await _wait_for_token(page, timeout_secs=2):
        return True

    if _capsolver_configured():
        sitekey = await page.evaluate(_TURNSTILE_SITEKEY_JS)
        if sitekey:
            meta = await page.evaluate(_TURNSTILE_META_JS)
            action = meta.get("action") or None
            cdata = meta.get("cdata") or None
            page_url = page.url
            try:
                token = await solve_turnstile_token(
                    settings.capsolver_api_key.strip(),
                    page_url,
                    sitekey,
                    action=str(action) if action else None,
                    cdata=str(cdata) if cdata else None,
                )
                await page.evaluate(_INJECT_TOKEN_JS, token)
                await asyncio.sleep(0.3)
                if await _wait_for_token(page, timeout_secs=8):
                    logger.info("[CAPTCHA] Turnstile solved via CapSolver ✓")
                    return True
                logger.warning("[CAPTCHA] CapSolver token injected but field not verified — retrying fallback")
            except CapSolverError as exc:
                logger.warning(f"[CAPTCHA] CapSolver failed: {exc}")
            except Exception as exc:
                logger.warning(f"[CAPTCHA] CapSolver unexpected error: {exc}")
        else:
            logger.warning("[CAPTCHA] Turnstile present but sitekey not found in DOM")

    logger.info("[CAPTCHA] Turnstile — waiting for browser auto-solve…")
    if await _wait_for_token(page, timeout_secs=25):
        logger.info("[CAPTCHA] Turnstile auto-solved ✓")
        return True

    logger.info("[CAPTCHA] Not auto-solved — trying checkbox click…")
    await _click_checkbox(page)
    if await _wait_for_token(page, timeout_secs=15):
        logger.info("[CAPTCHA] Turnstile solved after click ✓")
        return True

    logger.warning(
        "[CAPTCHA] Turnstile unsolved — set CAPSOLVER_API_KEY or use residential proxy."
    )
    return False


async def _wait_for_token(page: Page, timeout_secs: int) -> bool:
    """Poll until cf-turnstile-response has a value or iframe shows success."""
    for _ in range(max(1, timeout_secs * 2)):
        await asyncio.sleep(0.5)
        try:
            token = await page.evaluate(
                "() => (document.querySelector('textarea[name=\"cf-turnstile-response\"]') "
                "|| document.querySelector('input[name=\"cf-turnstile-response\"]') "
                "|| {}).value || ''"
            )
            if token and len(str(token)) > 20:
                logger.debug(f"[CAPTCHA] Token found in DOM ({len(str(token))} chars)")
                return True
        except Exception:
            pass

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
            await page.mouse.click(
                iframe_box["x"] + 24,
                iframe_box["y"] + iframe_box["height"] / 2,
            )
            logger.debug("[CAPTCHA] Clicked iframe (fallback)")
            return
    except Exception as exc:
        logger.debug(f"[CAPTCHA] Click failed: {exc}")
