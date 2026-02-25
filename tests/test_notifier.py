"""
tests/test_notifier.py — Unit tests for the Telegram notifier.
All Telegram API calls are mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from agent.models import Job, JobStatus


def make_won_job() -> Job:
    return Job(
        id="win-001",
        title="Fix leaking tap",
        description="Bathroom tap dripping.",
        suburb="Parramatta",
        state="NSW",
        budget=150.0,
        url="https://www.airtasker.com/tasks/win-001/",
        posted_at=datetime.utcnow(),
        status=JobStatus.WON,
        bid_price=150.0,
        distance_km=3.2,
        customer_phone="0412345678",
        customer_email="john@example.com",
        customer_name="Jane Smith",
    )


@pytest.mark.asyncio
async def test_send_win_calls_bot(monkeypatch):
    """send_win should call bot.send_message with the correct chat_id."""
    mock_bot = AsyncMock()
    monkeypatch.setattr("agent.notifier.Bot", lambda token: mock_bot)

    from agent.notifier import TelegramNotifier
    n = TelegramNotifier()
    job = make_won_job()
    await n.send_win(job)

    mock_bot.send_message.assert_awaited_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] is not None


@pytest.mark.asyncio
async def test_send_win_message_contains_phone(monkeypatch):
    """Win message should include the customer phone number."""
    sent_text = None

    async def capture(**kwargs):
        nonlocal sent_text
        sent_text = kwargs.get("text", "")

    mock_bot = AsyncMock()
    mock_bot.send_message = capture
    monkeypatch.setattr("agent.notifier.Bot", lambda token: mock_bot)

    from agent.notifier import TelegramNotifier
    n = TelegramNotifier()
    await n.send_win(make_won_job())

    assert sent_text is not None
    # Phone number should appear in the message
    assert "0412345678" in sent_text


@pytest.mark.asyncio
async def test_send_error_does_not_raise(monkeypatch):
    """send_error should never raise even if Telegram fails."""
    from telegram.error import TelegramError
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = TelegramError("network error")
    monkeypatch.setattr("agent.notifier.Bot", lambda token: mock_bot)

    from agent.notifier import TelegramNotifier
    n = TelegramNotifier()
    # Should not raise
    await n.send_error("Test context", "Something went wrong")


@pytest.mark.asyncio
async def test_escape_special_chars():
    """_escape should handle Telegram MarkdownV2 special characters."""
    from agent.notifier import TelegramNotifier
    n = TelegramNotifier()
    result = n._escape("Hello (World) [Test] #1!")
    assert "(" not in result.replace("\\(", "")  # parens are escaped
    assert "!" not in result.replace("\\!", "")
