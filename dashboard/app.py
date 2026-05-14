"""
dashboard/app.py — FastAPI dashboard backend.

Endpoints:
  GET /api/stats   — aggregate stats (jobs seen, bids, wins, earnings)
  GET /api/leads   — all recorded jobs, newest first
  GET /api/logs    — last 100 log lines
  GET /api/stream  — Server-Sent Events stream for live log tail
  GET /            — serves the single-page dashboard UI
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from agent.store import store, SessionStatus
from agent.session import session

app = FastAPI(title="AI Lead Agent Dashboard", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/api/stats")
async def get_stats():
    return JSONResponse(await store.get_stats())


@app.get("/api/leads")
async def get_leads():
    jobs = await store.all_jobs()
    return JSONResponse([j.to_dict() for j in reversed(jobs)])


@app.get("/api/logs")
async def get_logs():
    lines = await store.get_logs(last_n=200)
    return JSONResponse({"logs": lines})


@app.get("/api/stream")
async def log_stream(request: Request):
    """Server-Sent Events endpoint — streams new log lines to the browser."""
    async def generator():
        last_count = 0
        while True:
            if await request.is_disconnected():
                break
            lines = await store.get_logs(last_n=500)
            if len(lines) > last_count:
                new_lines = lines[last_count:]
                for line in new_lines:
                    yield {"data": json.dumps({"log": line})}
                last_count = len(lines)
            await asyncio.sleep(1)

    return EventSourceResponse(generator())


@app.get("/api/session/status")
async def get_session_status():
    status = await store.get_session_status()
    return JSONResponse({"status": status.value})


@app.post("/api/session/login")
async def trigger_login():
    # Run manual login in a background task to not block the API
    asyncio.create_task(session.manual_login())
    return JSONResponse({"message": "Manual login triggered"})


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
