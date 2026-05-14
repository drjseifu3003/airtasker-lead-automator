"""
stealth/capsolver_client.py — Async client for CapSolver Cloudflare Turnstile API.

Docs: https://docs.capsolver.com/guide/captcha/cloudflare_turnstile/
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

_CREATE = "https://api.capsolver.com/createTask"
_RESULT = "https://api.capsolver.com/getTaskResult"


class CapSolverError(Exception):
    """Raised when CapSolver returns an error response."""


async def solve_turnstile_token(
    client_key: str,
    website_url: str,
    website_key: str,
    *,
    action: str | None = None,
    cdata: str | None = None,
    poll_interval: float = 1.0,
    max_wait: float = 120.0,
) -> str:
    """
    Request a Turnstile token from CapSolver (AntiTurnstileTaskProxyLess).

    Raises CapSolverError on failure; returns the solution token string on success.
    """
    task: dict[str, Any] = {
        "type": "AntiTurnstileTaskProxyLess",
        "websiteURL": website_url,
        "websiteKey": website_key,
    }
    meta: dict[str, str] = {}
    if action:
        meta["action"] = action
    if cdata:
        meta["cdata"] = cdata
    if meta:
        task["metadata"] = meta

    payload = {"clientKey": client_key, "task": task}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        r = await client.post(_CREATE, json=payload)
        r.raise_for_status()
        data = r.json()

    err_id = data.get("errorId")
    if err_id not in (0, None):
        desc = data.get("errorDescription") or data.get("errorCode") or data
        raise CapSolverError(f"createTask failed: {desc}")

    task_id = data.get("taskId")
    if not task_id:
        raise CapSolverError(f"createTask missing taskId: {data}")

    tid = str(task_id)
    logger.info(f"[CAPSOLVER] Task created, polling result (id={tid[:8]}…)")

    elapsed = 0.0
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            r = await client.post(_RESULT, json={"clientKey": client_key, "taskId": tid})
            r.raise_for_status()
            res = r.json()

            if res.get("errorId") not in (0, None):
                desc = res.get("errorDescription") or res.get("errorCode") or res
                raise CapSolverError(f"getTaskResult error: {desc}")

            status = res.get("status")
            if status == "ready":
                token = (res.get("solution") or {}).get("token")
                if not token:
                    raise CapSolverError(f"ready but no token: {res}")
                logger.info("[CAPSOLVER] Turnstile token received ✓")
                return str(token)

            if status == "failed":
                raise CapSolverError(f"task failed: {res}")

    raise CapSolverError(f"timeout after {max_wait}s waiting for CapSolver")
