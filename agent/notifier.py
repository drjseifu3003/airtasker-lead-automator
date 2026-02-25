"""
agent/notifier.py — Telegram bot notifications for lead wins and errors.
"""
from __future__ import annotations

from loguru import logger
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from agent.models import Job
from config.settings import settings


class TelegramNotifier:
    """Sends rich Telegram messages when leads are won or errors occur."""

    def __init__(self) -> None:
        self._bot = Bot(token=settings.telegram_bot_token)
        self._chat_id = settings.telegram_chat_id

    async def send_win(self, job: Job) -> None:
        """Send a win notification with all customer details."""
        contact_info = ""
        if job.customer_phone:
            contact_info += f"📞 *Phone:* `{job.customer_phone}`\n"
        if job.customer_email:
            contact_info += f"📧 *Email:* `{job.customer_email}`\n"
        if not contact_info:
            contact_info = "⚠️ Contact not yet revealed — check app.\n"

        distance = f"{job.distance_km:.1f}km away" if job.distance_km else "Distance unknown"

        message = (
            "🏆 *LEAD WON\\!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Job:* {self._escape(job.title)}\n"
            f"📍 *Suburb:* {self._escape(job.suburb)} \\({distance}\\)\n"
            f"💰 *Bid:* ${job.bid_price:.0f}\n"
            f"🔗 [View Job]({job.url})\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{contact_info}"
        )

        await self._send(message)
        logger.info(f"[NOTIFIER] Win notification sent for job {job.id}")

    async def send_bid_placed(self, job: Job) -> None:
        """Confirmation that a bid was placed."""
        message = (
            "📤 *Bid Placed*\n"
            f"📋 {self._escape(job.title)}\n"
            f"📍 {self._escape(job.suburb)}\n"
            f"💰 ${job.bid_price:.0f} — waiting for response\\.\\.\\."
        )
        await self._send(message)

    async def send_error(self, context: str, error: str) -> None:
        """Alert operator of an agent error."""
        message = (
            "🚨 *Agent Error*\n"
            f"*Context:* {self._escape(context)}\n"
            f"*Error:* `{self._escape(error[:200])}`"
        )
        await self._send(message)

    async def send_startup(self) -> None:
        """Notify operator that the agent has started."""
        message = (
            "🤖 *AI Lead Agent Started*\n"
            "Monitoring Airtasker for new jobs\\.\n"
            "I'll notify you the moment we win a lead\\."
        )
        await self._send(message)

    async def _send(self, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
            )
        except TelegramError as exc:
            logger.error(f"[NOTIFIER] Failed to send Telegram message: {exc}")

    @staticmethod
    def _escape(text: str) -> str:
        """Escape special MarkdownV2 characters."""
        if not text:
            return ""
        specials = r"_*[]()~`>#+-=|{}.!\\"
        return "".join(f"\\{c}" if c in specials else c for c in str(text))


# Singleton
notifier = TelegramNotifier()
