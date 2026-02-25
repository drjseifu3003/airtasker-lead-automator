"""
main.py — Entry point for the AI Lead Automation agent.

Runs the Listener (job pipeline) and Dashboard (FastAPI) concurrently.

Usage:
    python main.py                     # production
    python main.py --dry-run           # listen + evaluate, never bid
    python main.py --dashboard-only    # just the dashboard (for testing UI)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn
from loguru import logger

from agent.listener import Listener
from agent.store import store
from config.settings import settings


def _configure_logging() -> None:
    """Set up loguru: console + file sink + in-memory store sink."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    )
    logger.add(
        "logs/agent_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
    )

    # Also funnel logs into the in-memory store for the dashboard
    async def _store_sink(message):
        await store.add_log(message.strip())

    # Sync wrapper (loguru sinks can be sync)
    def _sync_store_sink(message):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(store.add_log(str(message).strip()))
        except RuntimeError:
            pass  # No running loop yet

    logger.add(_sync_store_sink, level="INFO")


async def _run_dashboard() -> None:
    """Run the FastAPI dashboard."""
    # Import here to avoid circular issues before logging is set up
    from dashboard.app import app
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.dashboard_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_agent() -> None:
    listener = Listener()
    await listener.run()


async def _main(args: argparse.Namespace) -> None:
    if args.dry_run:
        # Override at runtime
        import os
        os.environ["DRY_RUN"] = "true"
        logger.info("🔬 DRY RUN mode — bids will NOT be submitted")

    if args.dashboard_only:
        logger.info(f"📊 Dashboard only — http://localhost:{settings.dashboard_port}")
        await _run_dashboard()
        return

    logger.info("🚀 Starting AI Lead Agent")
    logger.info(f"📊 Dashboard: http://localhost:{settings.dashboard_port}")

    # Run agent + dashboard together
    await asyncio.gather(
        _run_agent(),
        _run_dashboard(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Lead Automation Agent")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but never bid")
    parser.add_argument("--dashboard-only", action="store_true", help="Only run the dashboard")
    args = parser.parse_args()

    _configure_logging()

    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        logger.info("👋 Agent stopped by user")
