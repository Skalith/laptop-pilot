from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.messages import MessageType

from . import messages

if TYPE_CHECKING:
    from ..pipeline import Orchestrator

logger = logging.getLogger("orchestrator.bot.handlers")


class Sender:
    """Protocol for outbound Telegram messaging (async)."""

    async def send_message(self, user_id: int, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def send_approval(self, user_id: int, text: str, keyboard) -> None:  # pragma: no cover
        raise NotImplementedError


class NullSender(Sender):
    """No-op sender used when no Telegram token is configured (dev mode)."""

    async def send_message(self, user_id: int, text: str) -> None:
        logger.info("NullSender.send_message(user=%s): %s", user_id, text[:200])

    async def send_approval(self, user_id: int, text: str, keyboard) -> None:
        logger.info("NullSender.send_approval(user=%s): %s", user_id, text[:200])


def is_authorized(orchestrator: "Orchestrator", user_id: int) -> bool:
    return orchestrator.auth.is_authorized(user_id)


async def handle_telegram_message(
    orchestrator: "Orchestrator",
    sender: Sender,
    user_id: int,
    text: str,
) -> dict | None:
    """Route an inbound text message. Unauthorized senders are silently dropped."""
    if not is_authorized(orchestrator, user_id):
        logger.info("dropping message from unauthorized user %s", user_id)
        return None

    outcome = orchestrator.handle_request(user_id, text)
    await _send_outcome(orchestrator, sender, user_id, outcome)
    return outcome


async def handle_callback(
    orchestrator: "Orchestrator",
    sender: Sender,
    user_id: int,
    callback_data: str,
) -> dict | None:
    """Handle APPROVE/DISAPPROVE/EXECUTE/CANCEL button presses."""
    if not is_authorized(orchestrator, user_id):
        logger.info("dropping callback from unauthorized user %s", user_id)
        return None
    try:
        decision, phase, request_id = messages.parse_callback_data(callback_data)
    except ValueError as exc:
        logger.warning("bad callback data: %s", exc)
        return None

    if phase == 1:
        outcome = orchestrator.handle_approval_1(request_id, decision, user_id)
    else:
        outcome = orchestrator.handle_approval_2(request_id, decision, user_id)
    await _send_decision(sender, user_id, outcome)
    return outcome


async def handle_relay_message(
    orchestrator: "Orchestrator",
    sender: Sender,
    message: dict,
) -> dict | None:
    """Route Agent 2 traffic arriving at the orchestrator via the relay."""
    message_type = message.get("type")
    user_id = message.get("user_id") or orchestrator._request_users.get(message.get("request_id") or "")

    if message_type == MessageType.APPROVAL_2_PLAN:
        request_id = message.get("request_id") or ""
        plan = message.get("plan") or []
        outcome = orchestrator.handle_agent2_plan(request_id, plan, int(user_id or 0))
        if user_id:
            await sender.send_approval(
                int(user_id),
                messages.approval_two_text(request_id, plan, orchestrator.risk_for(request_id)),
                messages.approval_two_keyboard(request_id),
            )
        return outcome
    if message_type == MessageType.EXECUTION_RESULT:
        outcome = orchestrator.handle_agent2_result(message.get("request_id") or "", message)
        if user_id:
            await sender.send_message(int(user_id), messages.result_text(message))
        return outcome
    if message_type == MessageType.ERROR:
        if user_id:
            await sender.send_message(int(user_id), messages.error_text(message.get("error") or "unknown error"))
        return {"status": "error_to_user", "error": message.get("error")}
    return None


async def _send_outcome(orchestrator, sender, user_id, outcome) -> None:
    status = outcome.get("status")
    if status == "rejected":
        await sender.send_message(user_id, messages.error_text("You are not authorized."))
    elif status == "awaiting_approval_1":
        request_id = outcome["request_id"]
        await sender.send_approval(
            user_id,
            messages.approval_one_text(request_id, outcome["commands"], outcome.get("risk")),
            messages.approval_one_keyboard(request_id),
        )
    elif status == "dispatched":
        if outcome.get("auto_proceeded"):
            await sender.send_message(user_id, "Command auto-proceeded (low risk) and dispatched.")
        else:
            await sender.send_message(user_id, "Command dispatched to your laptop.")
    elif status == "error":
        await sender.send_message(user_id, messages.error_text(outcome.get("error") or "unknown error"))


async def _send_decision(sender, user_id, outcome) -> None:
    status = outcome.get("status")
    if status == "not_found":
        await sender.send_message(user_id, "No pending approval for that request (expired or already handled).")
    elif status == "executing":
        await sender.send_message(user_id, "Approved — execution signal sent to your laptop.")
    elif status == "stopped":
        await sender.send_message(user_id, "Cancelled. Nothing was executed.")
    elif status == "dispatched":
        await sender.send_message(user_id, "Approved — command dispatched to your laptop.")