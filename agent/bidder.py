"""
agent/bidder.py — Executes bid submission and post-win contact extraction.
"""
from __future__ import annotations

from loguru import logger

from agent.models import Job, JobStatus
from agent.notifier import notifier
from agent.session import SessionManager
from agent.store import store
from platforms.airtasker import AirtaskerPlatform


class Bidder:
    """Opens a fresh browser tab per bid to isolate navigation state."""

    def __init__(self, sess: SessionManager) -> None:
        self._session = sess
        self._platform = AirtaskerPlatform()

    async def submit(self, job: Job) -> None:
        """Full bid + post-win flow: open tab → bid → extract contact → notify → close tab."""
        job.status = JobStatus.BIDDING
        await store.update_job(job)

        tab = await self._session.new_tab()
        try:
            success = await self._platform.bid(
                tab, job, job.bid_message or "", job.bid_price or 0
            )
            if success:
                job.status = JobStatus.BID_SENT
                await store.update_job(job)
                await store.add_log(f"[BID] ✅ Bid sent: {job.title} | ${job.bid_price}")
                await notifier.send_bid_placed(job)

                # Try immediate contact extraction (in case it's auto-accept)
                job = await self._platform.extract_contact(tab, job)
                if job.customer_phone or job.customer_email:
                    job.status = JobStatus.WON
                    await store.update_job(job)
                    await store.add_log(f"[WIN] 🏆 {job.title} | {job.customer_phone}")
                    await notifier.send_win(job)
            else:
                job.status = JobStatus.FAILED
                await store.update_job(job)
                await store.add_log(f"[BID] ❌ Bid failed: {job.title}")
                await notifier.send_error(f"Bid failed: {job.title}", "Submission returned False")

        except Exception as exc:
            job.status = JobStatus.FAILED
            await store.update_job(job)
            logger.error(f"[BIDDER] Exception on job {job.id}: {exc}")
            await notifier.send_error(f"Bidder exception: {job.title}", str(exc))
        finally:
            await tab.close()
