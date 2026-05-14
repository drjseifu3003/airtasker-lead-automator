"""
platforms/airtasker.py — Airtasker platform adapter.

Handles:
  - WebSocket interception to catch new tasks in real-time.
  - XHR fallback interception on the /tasks feed.
  - Job payload parsing into the normalised Job dataclass.
  - Bid submission (humanised).
  - Contact extraction after lead is won.
"""
from __future__ import annotations

import asyncio
import json
import re
from asyncio import Queue
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from loguru import logger
from playwright.async_api import Page, WebSocket, Request, Response

from agent.models import Job, JobStatus
from platforms.base import BasePlatform
from stealth.behavior import human_click, human_type, random_sleep, random_scroll
from stealth.captcha import solve_captcha_if_present

BASE_URL = "https://www.airtasker.com"
BROWSE_URL = f"{BASE_URL}/tasks/?state=open"

# Regex patterns for Airtasker's internal API routes
_JOB_FEED_PATH_RE = re.compile(r"/api/v2/tasks|/graphql", re.IGNORECASE)
_JOB_ID_RE = re.compile(r'"id"\s*:\s*"?(\d+)"?')


class AirtaskerPlatform(BasePlatform):

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(self, page: Page) -> None:
        """Handled by SessionManager — nothing extra needed here."""
        pass

    # ── Listener ──────────────────────────────────────────────────────────────

    async def listen(self, page: Page, queue: Queue) -> None:
        """
        Navigate to the Airtasker task browse page and intercept:
          1. WebSocket frames containing task payloads.
          2. XHR responses from the /api/v2/tasks endpoint.

        Runs indefinitely — cancel the asyncio Task to stop.
        """
        logger.info("[AIRTASKER] Starting listener on browse page…")

        # Attach WebSocket listener BEFORE navigation
        page.on("websocket", lambda ws: asyncio.ensure_future(
            self._on_websocket(ws, queue)
        ))

        # Attach XHR/fetch response listener
        page.on("response", lambda resp: asyncio.ensure_future(
            self._on_response(resp, queue)
        ))

        await page.goto(BROWSE_URL, wait_until="networkidle", timeout=30_000)
        await solve_captcha_if_present(page)
        logger.info("[AIRTASKER] Browse page loaded — monitoring for new jobs…")

        # Keep the session alive: scroll occasionally, reload every 5 min
        while True:
            await random_sleep(30, 90)
            await random_scroll(page)
            await random_sleep(250, 350)  # ~5 minutes
            logger.debug("[AIRTASKER] Refreshing task feed…")
            await page.reload(wait_until="networkidle", timeout=30_000)
            await solve_captcha_if_present(page)

    async def _on_websocket(self, ws: WebSocket, queue: Queue) -> None:
        """Handle incoming WebSocket messages."""
        logger.debug(f"[AIRTASKER] WebSocket opened: {ws.url[:80]}")

        async def on_frame(payload: str) -> None:
            try:
                await self._process_raw_payload(payload, queue)
            except Exception as exc:
                logger.debug(f"[AIRTASKER] WS frame parse error: {exc}")

        ws.on("framereceived", lambda payload: asyncio.ensure_future(on_frame(payload)))

    async def _on_response(self, response: Response, queue: Queue) -> None:
        """Handle XHR/fetch responses from the tasks API."""
        url = response.url
        if not _JOB_FEED_PATH_RE.search(url):
            return
        if response.status not in (200, 201):
            return
        try:
            body = await response.text()
            await self._process_raw_payload(body, queue)
        except Exception as exc:
            logger.debug(f"[AIRTASKER] XHR parse error for {url}: {exc}")

    async def _process_raw_payload(self, raw: str, queue: Queue) -> None:
        """Parse raw JSON text, extract task objects, enqueue new ones."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        tasks = self._extract_tasks(data)
        for task_data in tasks:
            job = self._parse_task(task_data)
            if job and job.id not in self._seen_ids:
                self._seen_ids.add(job.id)
                logger.info(
                    f"[AIRTASKER] 🆕 New job: {job.title!r} in {job.suburb} — ${job.budget}"
                )
                await queue.put(job)

    def _extract_tasks(self, data: Any) -> list[dict]:
        """Recursively find task/task-like dicts in a nested payload."""
        tasks = []
        if isinstance(data, dict):
            # Direct task object
            if "id" in data and "name" in data and "location" in data:
                tasks.append(data)
            # Nested in common Airtasker response shapes
            for key in ("tasks", "task", "data", "items", "results", "edges", "node"):
                if key in data:
                    tasks.extend(self._extract_tasks(data[key]))
        elif isinstance(data, list):
            for item in data:
                tasks.extend(self._extract_tasks(item))
        return tasks

    def _parse_task(self, data: dict) -> Job | None:
        """Convert a raw Airtasker task dict into a normalised Job."""
        try:
            task_id = str(data.get("id", ""))
            if not task_id:
                return None

            # Location — Airtasker nests this under 'location' or 'suburb'
            location = data.get("location") or {}
            suburb = (
                location.get("suburb")
                or location.get("city")
                or data.get("suburb", "Unknown")
            )
            state = location.get("state", "NSW")
            lat = location.get("latitude") or location.get("lat")
            lng = location.get("longitude") or location.get("lng")

            # Budget
            budget_data = data.get("budget") or {}
            if isinstance(budget_data, dict):
                budget = float(budget_data.get("maximum") or budget_data.get("minimum") or 0)
            elif isinstance(budget_data, (int, float)):
                budget = float(budget_data)
            else:
                budget = None

            slug = data.get("slug") or task_id
            url = f"{BASE_URL}/tasks/{slug}/"

            return Job(
                id=task_id,
                title=data.get("name", "Untitled Task"),
                description=data.get("description", ""),
                suburb=suburb,
                state=state,
                budget=budget if budget else None,
                url=url,
                posted_at=datetime.utcnow(),
                lat=float(lat) if lat else None,
                lng=float(lng) if lng else None,
            )
        except Exception as exc:
            logger.debug(f"[AIRTASKER] Task parse error: {exc} | data keys: {list(data.keys())}")
            return None

    # ── Bidding ───────────────────────────────────────────────────────────────

    async def bid(self, page: Page, job: Job, message: str, price: float) -> bool:
        """
        Navigate to the job page and submit a bid.
        Uses humanised interactions throughout.
        """
        logger.info(f"[AIRTASKER] Bidding on {job.id}: {job.title!r} @ ${price}")
        try:
            await page.goto(job.url, wait_until="networkidle", timeout=30_000)
            await solve_captcha_if_present(page)
            await random_sleep(1.5, 3.0)
            await random_scroll(page)
            await random_sleep(0.5, 1.5)

            # Click the "Make an offer" / "Bid" button
            bid_btn_selector = (
                "button:has-text('Make an offer'), "
                "button:has-text('Place a bid'), "
                "button:has-text('Bid'), "
                "[data-testid='bid-button'], "
                "[data-ui='make-offer-button']"
            )
            await human_click(page, bid_btn_selector)
            await random_sleep(1.0, 2.0)

            # Fill bid amount
            price_input_selector = (
                "input[name='amount'], input[name='bid_amount'], "
                "input[placeholder*='amount'], input[placeholder*='price'], "
                "[data-testid='bid-amount-input']"
            )
            try:
                await human_type(page, price_input_selector, str(int(price)))
                await random_sleep(0.3, 0.8)
            except Exception:
                logger.debug("[AIRTASKER] Price field not found — may be fixed price task")

            # Fill bid message
            msg_selector = (
                "textarea[name='message'], textarea[name='description'], "
                "textarea[placeholder*='message'], textarea[placeholder*='introduce'], "
                "[data-testid='bid-message-input']"
            )
            await human_type(page, msg_selector, message)
            await random_sleep(1.0, 2.5)

            await solve_captcha_if_present(page)

            # Submit
            submit_selector = (
                "button[type='submit']:has-text('Send'), "
                "button:has-text('Submit offer'), "
                "button:has-text('Place bid'), "
                "[data-testid='submit-bid-button']"
            )
            await human_click(page, submit_selector)
            await random_sleep(2.0, 4.0)

            # Confirm success
            success_selector = (
                "[data-testid='bid-success'], "
                "text=Offer sent, text=Bid placed, text=offer has been sent"
            )
            try:
                await page.wait_for_selector(success_selector, timeout=8_000)
                logger.info(f"[AIRTASKER] ✅ Bid submitted successfully for {job.id}")
                return True
            except Exception:
                # Check if we're on a post-bid state anyway (URL change, etc.)
                if "offer" in page.url or "bid" in page.url:
                    logger.info(f"[AIRTASKER] ✅ Bid likely submitted (URL changed)")
                    return True
                logger.warning(f"[AIRTASKER] ⚠️ Bid success uncertain for {job.id}")
                return False

        except Exception as exc:
            logger.error(f"[AIRTASKER] Bid failed for {job.id}: {exc}")
            return False

    # ── Contact extraction ────────────────────────────────────────────────────

    async def extract_contact(self, page: Page, job: Job) -> Job:
        """
        After a lead is won/accepted, navigate to the task page and
        scrape the customer's phone number and email address.
        """
        try:
            await page.goto(job.url, wait_until="networkidle", timeout=20_000)
            await random_sleep(1, 2)

            content = await page.content()

            # Phone: Australian formats
            phone_match = re.search(
                r"(?:(?:\+?61|0)[\s.-]?)?(?:4\d{2}|[2378]\d{3})[\s.-]?\d{3}[\s.-]?\d{3,4}",
                content,
            )
            if phone_match:
                job.customer_phone = re.sub(r"[\s.-]", "", phone_match.group())

            # Email
            email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", content)
            if email_match:
                job.customer_email = email_match.group()

            # Customer name via API response capture
            name_el = await page.query_selector(
                "[data-testid='poster-name'], .poster-name, [class*='poster'] h3"
            )
            if name_el:
                job.customer_name = (await name_el.inner_text()).strip()

            logger.info(
                f"[AIRTASKER] Contact extracted: phone={job.customer_phone} email={job.customer_email}"
            )
        except Exception as exc:
            logger.error(f"[AIRTASKER] Contact extraction failed: {exc}")

        return job
