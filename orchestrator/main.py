from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from .bot.handlers import NullSender, Sender, handle_callback, handle_telegram_message
from .config import Settings
from .pipeline import Orchestrator, StubAgent1

logger = logging.getLogger("orchestrator.main")


def create_app(
    settings: Settings | None = None,
    *,
    agent1=None,
    dispatcher=None,
    sender: Sender | None = None,
) -> FastAPI:
    """Build the orchestrator FastAPI app.

    agent1 / dispatcher / sender are injectable (mocked in tests, real wiring in
    Part 4). ``sender`` sends Telegram text + approval keyboards.
    """
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()
    errors = settings.validate()
    if errors:
        raise RuntimeError(f"Orchestrator config missing required values: {', '.join(errors)}")
    orchestrator = Orchestrator(settings, agent1=agent1 or StubAgent1(), dispatcher=dispatcher)
    sender = sender or NullSender()

    app = FastAPI(title="LaptopPilot Orchestrator")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "pending_approvals": orchestrator.approvals.pending_count()}

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request) -> dict:
        """Telegram Bot webhook: routes text updates and inline-keyboard callbacks."""
        update = await request.json()
        message = update.get("message") or update.get("edited_message")
        callback = update.get("callback_query")

        if message is not None:
            user_id = message.get("from", {}).get("id")
            text = message.get("text")
            if user_id is None or text is None:
                return {"status": "ignored"}
            await handle_telegram_message(orchestrator, sender, user_id, text)
            return {"status": "ok"}

        if callback is not None:
            user_id = callback.get("from", {}).get("id")
            data = callback.get("data")
            if user_id is None or data is None:
                return {"status": "ignored"}
            await handle_callback(orchestrator, sender, user_id, data)
            return {"status": "ok"}

        return {"status": "ignored"}

    # Expose the pipeline for callers (bot wiring, tests)
    app.state.orchestrator = orchestrator
    app.state.sender = sender
    return app