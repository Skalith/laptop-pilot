"""Production runner: Telegram polling + relay client + real Agent 1.

Usage:
    python -m orchestrator.runner

Reads configuration from the environment (or a sourced ``.env``). The bot uses
long polling, so the laptop does not need a public URL or inbound ports.
"""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from agent1.agent import Agent1
from shared.llm.factory import create_llm
from shared.messages import MessageType, envelope
from shared.net import RelayClient

from .bot.handlers import handle_relay_message
from .bot.telegram_bot import TelegramBot
from .config import Settings
from .pipeline import Orchestrator

logger = logging.getLogger("orchestrator.runner")


def build(settings: Settings) -> tuple[RelayClient, Orchestrator, TelegramBot]:
    """Wire the real Agent 1, relay dispatcher, and Telegram bot together."""
    relay = RelayClient(
        settings.relay_url,
        settings.relay_secret,
        path="/ws/orchestrator",
    )

    def dispatcher(commands: list[dict], request_id: str) -> None:
        asyncio.get_running_loop().create_task(
            relay.publish(
                envelope(
                    MessageType.DISPATCH_COMMAND,
                    request_id=request_id,
                    user_id=orchestrator.request_user(request_id),
                    commands=commands,
                )
            )
        )

    def execute_signal(request_id: str) -> None:
        asyncio.get_running_loop().create_task(
            relay.publish(envelope(MessageType.EXECUTE_SIGNAL, request_id=request_id))
        )

    orchestrator = Orchestrator(
        settings,
        agent1=Agent1(create_llm(settings.llm)),
        dispatcher=dispatcher,
        execute_signal=execute_signal,
    )
    bot = TelegramBot(settings.telegram_bot_token, orchestrator)

    async def on_message(message: dict) -> None:
        try:
            await handle_relay_message(orchestrator, bot.sender, message)
        except Exception:
            logger.exception("failed to handle relay message: %s", message.get("type"))

    relay.on_message = on_message
    return relay, orchestrator, bot


async def _run() -> None:
    load_dotenv()
    settings = Settings.from_env()
    errors = settings.validate()
    if not settings.telegram_bot_token:
        errors.append("TELEGRAM_BOT_TOKEN")
    if errors:
        raise SystemExit(f"Orchestrator config missing required values: {', '.join(errors)}")

    relay, orchestrator, bot = build(settings)
    relay_task = asyncio.create_task(relay.run())

    await bot.app.initialize()
    await bot.app.start()
    assert bot.app.updater is not None
    await bot.app.updater.start_polling()
    logger.info("LaptopPilot orchestrator running (Telegram polling)")

    try:
        await asyncio.Event().wait()
    finally:
        await bot.app.updater.stop()
        await bot.app.stop()
        await bot.app.shutdown()
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        await relay.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
