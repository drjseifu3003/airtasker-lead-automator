"""
agent/listener.py — Real-time job interception coordinator.

Drives the listen → evaluate → bid → notify pipeline.
"""
from __future__ import annotations

import asyncio
from asyncio import Queue

from loguru import logger

from agent.evaluator import evaluate
from agent.models import Job, JobStatus
from agent.notifier import notifier
from agent.session import session
from agent.store import store
from agent.bidder import Bidder
from config.settings import settings
from config.settings import load_profile
from platforms.airtasker import AirtaskerPlatform


class Listener:
    """
    Main orchestrator.  Runs:
      - Platform listener  (produces Jobs onto a queue)
      - Worker pool         (consumes Jobs: evaluate → bid → notify)
    """

    def __init__(self, profile_path: str = "config/profiles/default.json") -> None:
        self._profile = load_profile(profile_path)
        self._platform = AirtaskerPlatform()
        self._queue: Queue[Job] = Queue()
        self._bidder: Bidder | None = None
        self._active_bids = 0

    async def run(self) -> None:
        logger.info("[LISTENER] Starting AI Lead Agent…")
        await notifier.send_startup()

        # Boot the authenticated browser session
        while True:
            try:
                page = await session.start()
                break
            except Exception as exc:
                logger.error(f"[LISTENER] Session start failed: {exc} — retrying in 20s")
                await notifier.send_error("Session start failed", str(exc))
                await asyncio.sleep(20)
        self._bidder = Bidder(session)

        # Run listener + workers concurrently
        await asyncio.gather(
            self._listen_loop(page),
            self._worker_loop(),
            self._worker_loop(),   # 2 parallel evaluate/bid workers
        )

    async def _listen_loop(self, page) -> None:
        """Run the platform listener — pushes jobs onto the queue."""
        while True:
            try:
                await self._platform.listen(page, self._queue)
            except Exception as exc:
                logger.error(f"[LISTENER] Listener crashed: {exc} — restarting in 10s")
                await notifier.send_error("Listener crashed", str(exc))
                await asyncio.sleep(10)
                # Re-get page (re-login if needed)
                page = await session.get_page()

    async def _worker_loop(self) -> None:
        """Consume jobs from the queue, evaluate, and bid."""
        while True:
            job: Job = await self._queue.get()
            try:
                await self._process(job)
            except Exception as exc:
                logger.error(f"[LISTENER] Worker error on {job.id}: {exc}")
            finally:
                self._queue.task_done()

    async def _process(self, job: Job) -> None:
        """Full pipeline for a single job: dedup → evaluate → bid → notify."""
        # Dedup
        if await store.is_seen(job.id):
            return
        await store.add_job(job)
        await store.add_log(f"[NEW] {job.title} | {job.suburb} | ${job.budget}")

        # Check daily bid cap
        stats = await store.get_stats()
        max_daily = self._profile.get("max_daily_bids", 20)
        if stats["bids_sent"] >= max_daily:
            logger.info(f"[LISTENER] Daily bid cap ({max_daily}) reached — skipping {job.id}")
            job.status = JobStatus.SKIPPED
            await store.update_job(job)
            return

        # Evaluate
        job = await evaluate(job, self._profile)
        await store.update_job(job)
        await store.add_log(
            f"[EVAL] {job.title} → {'BID' if job.ai_approved else f'SKIP ({job.skip_reason})'}"
        )

        if not job.ai_approved:
            return

        if settings.dry_run:
            logger.info(f"[LISTENER] DRY RUN — would bid ${job.bid_price} on {job.id}")
            job.status = JobStatus.BID_SENT   # simulate
            await store.update_job(job)
            return

        # Bid
        await self._bidder.submit(job)
        await store.update_job(job)
