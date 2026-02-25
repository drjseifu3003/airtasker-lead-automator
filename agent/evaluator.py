"""
agent/evaluator.py — GPT-4o-mini powered job evaluation & bid generation.

For each intercepted job:
  1. Geocode the suburb and compute distance from the carpenter's home.
  2. Estimate effort and check min hourly rate.
  3. Ask GPT-4o-mini to confirm skill match and write a persuasive bid.
"""
from __future__ import annotations

import json
import math
from typing import Optional

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from loguru import logger
from openai import AsyncOpenAI

from agent.models import Job, JobStatus, SkipReason
from config.settings import settings

_geocoder = Nominatim(user_agent="ai-leads-agent/1.0")
_openai = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url or None,  # None = default OpenAI endpoint
)


# ── Geo helpers ───────────────────────────────────────────────────────────────

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in kilometres."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _geocode_suburb(suburb: str, state: str) -> Optional[tuple[float, float]]:
    """Return (lat, lng) for a suburb, or None on failure."""
    query = f"{suburb}, {state}, Australia"
    try:
        location = _geocoder.geocode(query, timeout=5)
        if location:
            return location.latitude, location.longitude
    except GeocoderTimedOut:
        logger.warning(f"Geocoder timed out for: {query}")
    return None


# ── AI evaluation ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert assistant that evaluates tradespeople's job leads.
You will receive a job posting and a carpenter's profile.
Respond ONLY with a JSON object — no markdown, no explanation outside the JSON.

Response format:
{
  "approved": true|false,
  "skip_reason": null | "skill_mismatch" | "below_min_rate" | "ai_rejected",
  "estimated_hours": <number>,
  "bid_price": <number>,
  "bid_message": "<personalized message, max 3 sentences>",
  "reasoning": "<brief internal note>"
}

Rules:
- If the job clearly requires a skill NOT in the carpenter's skill list, set approved=false, skip_reason="skill_mismatch".
- If the budget or expected payout is below min_hourly_rate × estimated_hours, set approved=false, skip_reason="below_min_rate".
- Otherwise, approve and generate a warm, persuasive bid_message that mentions the suburb and job type.
- bid_message must sound human, brief, and confident. No emojis.
"""


async def evaluate(job: Job, profile: dict) -> Job:
    """
    Evaluate a job against the carpenter profile.
    Mutates and returns the job with updated status, bid_message, bid_price.
    """
    job.status = JobStatus.EVALUATING
    logger.info(f"[EVALUATOR] Evaluating job {job.id}: {job.title!r} in {job.suburb}")

    # ── Step 1: Distance filter ───────────────────────────────────────────────
    if job.lat is None or job.lng is None:
        coords = _geocode_suburb(job.suburb, job.state)
        if coords:
            job.lat, job.lng = coords

    if job.lat and job.lng:
        job.distance_km = round(
            _haversine(profile["home_lat"], profile["home_lng"], job.lat, job.lng), 1
        )
        if job.distance_km > profile["radius_km"]:
            logger.info(
                f"[EVALUATOR] SKIP — too far: {job.distance_km}km > {profile['radius_km']}km"
            )
            job.status = JobStatus.SKIPPED
            job.skip_reason = SkipReason.OUTSIDE_RADIUS
            job.ai_approved = False
            return job

    # ── Step 2: Quick keyword exclusion ──────────────────────────────────────
    desc_lower = (job.title + " " + job.description).lower()
    for excluded in profile.get("excluded_skills", []):
        if excluded.lower() in desc_lower:
            logger.info(f"[EVALUATOR] SKIP — excluded keyword: {excluded!r}")
            job.status = JobStatus.SKIPPED
            job.skip_reason = SkipReason.SKILL_MISMATCH
            job.ai_approved = False
            return job

    # ── Step 3: GPT-4o-mini evaluation ───────────────────────────────────────
    user_message = json.dumps({
        "job": {
            "title": job.title,
            "description": job.description,
            "suburb": job.suburb,
            "budget": job.budget,
        },
        "profile": {
            "name": profile["name"],
            "skills": profile["skills"],
            "excluded_skills": profile.get("excluded_skills", []),
            "min_hourly_rate": profile["min_hourly_rate"],
            "home_suburb": profile["home_suburb"],
            "bid_template_hint": profile.get("bid_template", ""),
        },
    }, indent=2)

    try:
        response = await _openai.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=400,
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.error(f"[EVALUATOR] OpenAI error: {exc}")
        job.status = JobStatus.SKIPPED
        job.skip_reason = SkipReason.AI_REJECTED
        job.ai_approved = False
        return job

    job.ai_approved = result.get("approved", False)
    if not job.ai_approved:
        reason_str = result.get("skip_reason", "ai_rejected")
        try:
            job.skip_reason = SkipReason(reason_str)
        except ValueError:
            job.skip_reason = SkipReason.AI_REJECTED
        job.status = JobStatus.SKIPPED
        logger.info(
            f"[EVALUATOR] SKIP — AI rejected: {result.get('reasoning', '')}"
        )
    else:
        job.bid_price = float(result.get("bid_price") or profile["default_bid_price"])
        job.bid_message = result.get("bid_message", "").strip()
        logger.info(
            f"[EVALUATOR] APPROVE — bid ${job.bid_price} | {job.bid_message[:60]}…"
        )

    return job
