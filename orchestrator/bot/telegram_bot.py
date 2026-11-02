from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import messages
from .handlers import Sender, handle_callback, handle_telegram_message

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ExtBot

    from ..pipeline import Orchestrator

logger = logging.getLogger("orchestrator.bot.telegram_bot")

PARSE_MODE = messages.PARSE_MODE_HTML


class TelegramSender(Sender):
    """Outbound sender backed by python-telegram-bot's Bot."""

    def __init__(self, bot: "ExtBot"):
        self.bot = bot

    async def send_message(self, user_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=user_id, text=text, parse_mode=PARSE_MODE)

    async def send_approval(self, user_id: int, text: str, keyboard) -> None:
        await self.bot.send_message(chat_id=user_id, text=text, parse_mode=PARSE_MODE, reply_markup=keyboard)


class TelegramBot:
    """Webhook-mode Telegram bot wired to the orchestrator.

    ``on_authorized`` guard: inbound updates from non-allow-listed users are
    dropped before they reach the orchestrator.
    """

    def __init__(
        self,
        token: str,
        orchestrator: "Orchestrator",
        *,
        sender: Sender | None = None,
    ) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required to start the bot")
        self.orchestrator = orchestrator
        self.app: Application = ApplicationBuilder().token(token).build()
        self.sender = sender or TelegramSender(self.app.bot)

        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._on_text))
        self.app.add_handler(CallbackQueryHandler(self._on_callback))

    def _authorized(self, user_id: int | None) -> bool:
        return user_id is not None and self.orchestrator.auth.is_authorized(user_id)

    async def _on_text(self, update: "Update", context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not self._authorized(user.id if user else None):
            logger.info("dropping message from unauthorized user")
            return
        await handle_telegram_message(self.orchestrator, self.sender, user.id, update.message.text)

    async def _on_callback(self, update: "Update", context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not self._authorized(user.id if user else None):
            await update.callback_query.answer(text="Not authorized", show_alert=True)
            return
        await handle_callback(self.orchestrator, self.sender, user.id, update.callback_query.data)
        await update.callback_query.answer()

    def run_webhook(self, *, webhook_url: str, port: int, path: str = "telegram/webhook", secret_token: str = "") -> None:
        """Serve the webhook (blocking). Requires the token to be valid at runtime."""
        self.app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=path.rstrip("/").lstrip("/"),
            webhook_url=webhook_url.rstrip("/") + "/" + path.strip("/"),
            secret_token=secret_token or None,
        )

    async def set_webhook(self, url: str, secret_token: str | None = None) -> None:
        try:
            await self.app.bot.set_webhook(url=url, secret_token=secret_token)
        except TelegramError as exc:  # frozenset-like wrap
            raise TelegramError(f"set_webhook failed: {exc}") from exc