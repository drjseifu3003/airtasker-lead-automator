"""
platforms/base.py — Abstract base class for platform adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Queue

from playwright.async_api import Page

from agent.models import Job


class BasePlatform(ABC):
    """All platform adapters implement this interface."""

    @abstractmethod
    async def login(self, page: Page) -> None:
        """Authenticate with the platform (if not already logged in)."""
        ...

    @abstractmethod
    async def listen(self, page: Page, queue: Queue) -> None:
        """
        Start listening for new job postings.
        Push Job objects onto `queue` as they arrive.
        This method runs indefinitely (use asyncio.Task to cancel).
        """
        ...

    @abstractmethod
    async def bid(self, page: Page, job: Job, message: str, price: float) -> bool:
        """
        Submit a bid for `job`.
        Returns True on success, False if bid submission failed.
        """
        ...

    @abstractmethod
    async def extract_contact(self, page: Page, job: Job) -> Job:
        """
        After winning a lead, extract customer phone/email from the page.
        Returns the mutated job with contact details populated.
        """
        ...
