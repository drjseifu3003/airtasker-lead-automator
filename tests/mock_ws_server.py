"""
tests/mock_ws_server.py — Tiny asyncio WebSocket server that emits
fake Airtasker-style job payloads for testing the listener without
touching the real platform.

Run standalone:  python tests/mock_ws_server.py
"""
from __future__ import annotations

import asyncio
import json
import random
import string
from datetime import datetime

SUBURBS = ["Parramatta", "Blacktown", "Penrith", "Liverpool", "Bankstown", "Ryde"]
TITLES = [
    "Fix garden deck boards",
    "Build timber pergola",
    "Fence replacement — 15m",
    "Floating floor installation",
    "Wardrobe assembly and fit",
    "Deck sanding and staining",
]

PORT = 8765


def _random_id() -> str:
    return "".join(random.choices(string.digits, k=8))


def _make_job_payload() -> dict:
    suburb = random.choice(SUBURBS)
    return {
        "type": "task.created",
        "task": {
            "id": _random_id(),
            "name": random.choice(TITLES),
            "description": "This is a mock job for testing purposes.",
            "location": {
                "suburb": suburb,
                "state": "NSW",
                "latitude": -33.8136 + random.uniform(-0.2, 0.2),
                "longitude": 151.0034 + random.uniform(-0.2, 0.2),
            },
            "budget": {"minimum": 100, "maximum": random.choice([150, 200, 300, 500])},
            "slug": f"mock-task-{_random_id()}",
        },
    }


async def _handler(websocket) -> None:
    print(f"[MOCK-WS] Client connected: {websocket.remote_address}")
    try:
        while True:
            payload = _make_job_payload()
            await websocket.send(json.dumps(payload))
            print(f"[MOCK-WS] Sent: {payload['task']['name']} in {payload['task']['location']['suburb']}")
            await asyncio.sleep(random.uniform(5, 15))
    except Exception as exc:
        print(f"[MOCK-WS] Client disconnected: {exc}")


async def main() -> None:
    try:
        import websockets
    except ImportError:
        print("Install websockets: pip install websockets")
        return

    print(f"[MOCK-WS] Listening on ws://localhost:{PORT}")
    async with websockets.serve(_handler, "localhost", PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
