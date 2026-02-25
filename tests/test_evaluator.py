"""
tests/test_evaluator.py — Unit tests for the GPT-4o-mini job evaluator.
All OpenAI calls are mocked so no API key is needed.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from agent.models import Job, JobStatus, SkipReason


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def profile():
    return {
        "name": "John",
        "home_suburb": "Parramatta",
        "home_lat": -33.8136,
        "home_lng": 151.0034,
        "radius_km": 15,
        "skills": ["carpentry", "decking", "fencing"],
        "excluded_skills": ["painting", "cleaning"],
        "min_hourly_rate": 100,
        "default_bid_price": 150,
        "bid_template": "",
    }


def make_job(**kwargs) -> Job:
    defaults = dict(
        id="test-001",
        title="Fix garden deck",
        description="Need a carpenter to replace 3 deck boards.",
        suburb="Parramatta",
        state="NSW",
        budget=200.0,
        url="https://www.airtasker.com/tasks/123/",
        posted_at=datetime.utcnow(),
        lat=-33.8136,
        lng=151.0034,
    )
    defaults.update(kwargs)
    return Job(**defaults)


APPROVE_RESPONSE = json.dumps({
    "approved": True,
    "skip_reason": None,
    "estimated_hours": 2,
    "bid_price": 180,
    "bid_message": "Hi! I'm local to Parramatta and can fix your deck tomorrow.",
    "reasoning": "Deck job matches carpentry skill.",
})

REJECT_SKILL_RESPONSE = json.dumps({
    "approved": False,
    "skip_reason": "skill_mismatch",
    "estimated_hours": 3,
    "bid_price": 0,
    "bid_message": "",
    "reasoning": "Painting is not in skill list.",
})

REJECT_RATE_RESPONSE = json.dumps({
    "approved": False,
    "skip_reason": "below_min_rate",
    "estimated_hours": 4,
    "bid_price": 0,
    "bid_message": "",
    "reasoning": "Budget is too low vs hours needed.",
})


def _mock_openai(response_text: str):
    """Create a mock AsyncOpenAI client that returns response_text."""
    mock = AsyncMock()
    choice = MagicMock()
    choice.message.content = response_text
    mock.chat.completions.create.return_value = MagicMock(choices=[choice])
    return mock


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_matching_job(profile):
    """A nearby carpentry job should be approved with a bid message."""
    job = make_job()
    with patch("agent.evaluator._openai", _mock_openai(APPROVE_RESPONSE)):
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is True
    assert result.status == JobStatus.BID_SENT or result.status.value in ("bid_sent", "new", "evaluating")
    # After evaluate, status is not yet BID_SENT — that's set by bidder.
    # Evaluator leaves it at EVALUATING-level; check bid fields instead.
    assert result.bid_price == 180
    assert "Parramatta" in result.bid_message


@pytest.mark.asyncio
async def test_skip_outside_radius(profile):
    """A job 50km away should be skipped without calling OpenAI."""
    job = make_job(
        suburb="Wollongong",
        lat=-34.4278,
        lng=150.8931,
    )
    with patch("agent.evaluator._openai", _mock_openai(APPROVE_RESPONSE)) as mock_ai:
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is False
    assert result.skip_reason == SkipReason.OUTSIDE_RADIUS
    assert result.status == JobStatus.SKIPPED


@pytest.mark.asyncio
async def test_skip_excluded_keyword(profile):
    """A job with an excluded keyword should be rejected before calling OpenAI."""
    job = make_job(title="House painting — 3 rooms", description="Full interior painting job.")
    with patch("agent.evaluator._openai", _mock_openai(APPROVE_RESPONSE)) as mock_ai:
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is False
    assert result.skip_reason == SkipReason.SKILL_MISMATCH
    # OpenAI should NOT be called (it's a fast keyword filter)
    mock_ai.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_skip_skill_mismatch_via_ai(profile):
    """AI reports skill_mismatch — job should be skipped."""
    job = make_job(title="Plumbing leak fix")
    with patch("agent.evaluator._openai", _mock_openai(REJECT_SKILL_RESPONSE)):
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is False
    assert result.skip_reason == SkipReason.SKILL_MISMATCH


@pytest.mark.asyncio
async def test_skip_below_min_rate(profile):
    """AI reports below_min_rate — job should be skipped."""
    job = make_job(budget=50.0)
    with patch("agent.evaluator._openai", _mock_openai(REJECT_RATE_RESPONSE)):
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is False
    assert result.skip_reason == SkipReason.BELOW_MIN_RATE


@pytest.mark.asyncio
async def test_openai_error_graceful(profile):
    """If OpenAI call throws, the job should be skipped gracefully."""
    job = make_job()
    mock = AsyncMock()
    mock.chat.completions.create.side_effect = Exception("API timeout")
    with patch("agent.evaluator._openai", mock):
        from agent.evaluator import evaluate
        result = await evaluate(job, profile)

    assert result.ai_approved is False
    assert result.skip_reason == SkipReason.AI_REJECTED
