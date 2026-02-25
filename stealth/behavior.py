"""
stealth/behavior.py — Human-like interaction helpers for Playwright.

All interactions add realistic randomised delays and mouse movements
to avoid the robotic timing patterns that bot-detection systems flag.
"""
from __future__ import annotations

import asyncio
import random

from loguru import logger
from playwright.async_api import Page


async def random_sleep(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Sleep for a gaussian-distributed duration between min_s and max_s seconds."""
    mid = (min_s + max_s) / 2
    sigma = (max_s - min_s) / 6
    duration = max(min_s, min(max_s, random.gauss(mid, sigma)))
    await asyncio.sleep(duration)


async def human_type(page: Page, selector: str, text: str, timeout: int = 15_000) -> None:
    """
    Click a field, clear it, then type text character-by-character with
    realistic inter-keystroke delays (50–200ms).
    Uses page.locator() which handles scrolling into view automatically.
    """
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=timeout)
    await locator.scroll_into_view_if_needed()
    await random_sleep(0.2, 0.5)
    await locator.click()
    await random_sleep(0.1, 0.3)
    await locator.fill("")          # clear existing content
    await random_sleep(0.1, 0.2)
    for char in text:
        await locator.type(char, delay=random.randint(50, 200))
    logger.debug(f"[BEHAVIOR] Typed {len(text)} chars into {selector!r}")


async def human_click(page: Page, selector: str, timeout: int = 15_000) -> None:
    """
    Scroll an element into view, move the mouse to it with jitter, then click.
    Falls back to force-click if the element is obscured by an overlay.
    """
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=timeout)
    await locator.scroll_into_view_if_needed()
    await random_sleep(0.1, 0.3)

    # Try to get bounding box for realistic mouse movement
    box = await locator.bounding_box()
    if box:
        jitter_x = random.uniform(box["x"] + box["width"] * 0.2,
                                   box["x"] + box["width"] * 0.8)
        jitter_y = random.uniform(box["y"] + box["height"] * 0.2,
                                   box["y"] + box["height"] * 0.8)
        await page.mouse.move(jitter_x, jitter_y)
        await random_sleep(0.05, 0.2)

    try:
        await locator.click(timeout=10_000)
    except Exception:
        # Fallback: force-click bypasses visibility / interactability checks
        logger.warning(f"[BEHAVIOR] Normal click failed on {selector!r}, trying force click")
        await locator.click(force=True, timeout=10_000)

    logger.debug(f"[BEHAVIOR] Clicked {selector!r}")


async def random_scroll(page: Page) -> None:
    """Scroll the page a random amount to simulate reading."""
    scroll_px = random.randint(200, 800)
    direction = random.choice([1, 1, -1])   # mostly scroll down
    await page.evaluate(f"window.scrollBy(0, {scroll_px * direction})")
    await random_sleep(0.3, 1.0)


async def move_mouse_randomly(page: Page) -> None:
    """Move the mouse to a random screen position (simulates idle activity)."""
    vp = page.viewport_size or {"width": 1280, "height": 800}
    x = random.randint(100, vp["width"] - 100)
    y = random.randint(100, vp["height"] - 100)
    await page.mouse.move(x, y)
    await random_sleep(0.1, 0.4)
