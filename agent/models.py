"""
agent/models.py — Shared data models used across the agent pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    NEW = "new"
    EVALUATING = "evaluating"
    SKIPPED = "skipped"
    BIDDING = "bidding"
    BID_SENT = "bid_sent"
    WON = "won"
    FAILED = "failed"


class SkipReason(str, Enum):
    OUTSIDE_RADIUS = "outside_radius"
    BELOW_MIN_RATE = "below_min_rate"
    SKILL_MISMATCH = "skill_mismatch"
    ALREADY_SEEN = "already_seen"
    MAX_BIDS_REACHED = "max_bids_reached"
    AI_REJECTED = "ai_rejected"


@dataclass
class Job:
    """Normalised job/task record intercepted from Airtasker."""
    id: str
    title: str
    description: str
    suburb: str
    state: str
    budget: Optional[float]          # Posted budget (may be None/"open")
    platform: str = "airtasker"
    url: str = ""
    posted_at: datetime = field(default_factory=datetime.utcnow)
    lat: Optional[float] = None
    lng: Optional[float] = None

    # Populated after evaluation
    status: JobStatus = JobStatus.NEW
    skip_reason: Optional[SkipReason] = None
    ai_approved: Optional[bool] = None
    bid_message: Optional[str] = None
    bid_price: Optional[float] = None
    distance_km: Optional[float] = None

    # Populated after winning
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "suburb": self.suburb,
            "state": self.state,
            "budget": self.budget,
            "platform": self.platform,
            "url": self.url,
            "posted_at": self.posted_at.isoformat(),
            "lat": self.lat,
            "lng": self.lng,
            "status": self.status.value,
            "skip_reason": self.skip_reason.value if self.skip_reason else None,
            "ai_approved": self.ai_approved,
            "bid_message": self.bid_message,
            "bid_price": self.bid_price,
            "distance_km": self.distance_km,
            "customer_phone": self.customer_phone,
            "customer_email": self.customer_email,
            "customer_name": self.customer_name,
        }
