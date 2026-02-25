"""
agent/store.py — In-memory job store shared between agent and dashboard.
Thread-safe via asyncio locks. Acts as single source of truth for all
intercepted jobs, stats, and log lines.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional

from agent.models import Job, JobStatus


class JobStore:
    """Shared, in-process store for all intercepted jobs and stats."""

    MAX_LOG_LINES = 500

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._jobs: Dict[str, Job] = {}           # job_id → Job
        self._order: List[str] = []               # insertion order
        self._logs: Deque[str] = deque(maxlen=self.MAX_LOG_LINES)
        self._started_at: datetime = datetime.utcnow()

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def add_job(self, job: Job) -> bool:
        """Add a job if not already present. Returns True if added."""
        async with self._lock:
            if job.id in self._jobs:
                return False
            self._jobs[job.id] = job
            self._order.append(job.id)
            return True

    async def update_job(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.id] = job

    async def get_job(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def all_jobs(self) -> List[Job]:
        async with self._lock:
            return [self._jobs[jid] for jid in self._order]

    async def is_seen(self, job_id: str) -> bool:
        async with self._lock:
            return job_id in self._jobs

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        async with self._lock:
            jobs = list(self._jobs.values())
        total = len(jobs)
        bids = sum(1 for j in jobs if j.status in (
            JobStatus.BIDDING, JobStatus.BID_SENT, JobStatus.WON))
        won = sum(1 for j in jobs if j.status == JobStatus.WON)
        win_rate = round(won / bids * 100, 1) if bids else 0
        est_earnings = sum(
            (j.bid_price or 0) for j in jobs if j.status == JobStatus.WON
        )
        return {
            "total_seen": total,
            "bids_sent": bids,
            "won": won,
            "win_rate": win_rate,
            "est_earnings": est_earnings,
            "uptime_seconds": int((datetime.utcnow() - self._started_at).total_seconds()),
        }

    # ── Logs ─────────────────────────────────────────────────────────────────

    async def add_log(self, line: str) -> None:
        async with self._lock:
            self._logs.append(line)

    async def get_logs(self, last_n: int = 100) -> List[str]:
        async with self._lock:
            lines = list(self._logs)
        return lines[-last_n:]


# Global singleton — import from anywhere
store = JobStore()
