from __future__ import annotations

import asyncio

import pytest

from agent1.agent import Agent1, LLMValidationError
from agent1.parser import ParseError
from orchestrator.bot import handlers
from orchestrator.bot.messages import approval_one_keyboard
from orchestrator.config import Settings
from orchestrator.pipeline import Orchestrator


class FakeLLM:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def generate_json(self, *, system, user, max_tokens=1024):
        if not self.payloads:
            raise RuntimeError("no payload queued")
        return self.payloads.pop(0)


BASE_CONTEXT = {"cwd": "~/", "conversation_history": [], "last_known_laptop_state": None}

VALID = {
    "commands": [
        {"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"},
    ]
}


class FakeSender:
    def __init__(self):
        self.messages: list[tuple[int, str]] = []
        self.approvals: list[tuple[int, str, object]] = []

    async def send_message(self, user_id, text):
        self.messages.append((user_id, text))

    async def send_approval(self, user_id, text, keyboard):
        self.approvals.append((user_id, text, keyboard))


class FakeDispatcher:
    def __init__(self):
        self.calls: list[tuple[list, str]] = []

    def __call__(self, commands, request_id):
        self.calls.append((commands, request_id))


def build(tmp_path, *, agent1=None, dispatcher=None):
    settings = Settings(
        authorized_user_ids={111},
        relay_secret="s",
        relay_url="ws://x",
        log_path=str(tmp_path / "audit.log"),
    )
    orch = Orchestrator(settings, agent1=agent1, dispatcher=dispatcher)
    sender = FakeSender()
    return orch, sender


def run(coro):
    return asyncio.run(coro)


class TestMessageRouting:
    def test_authorized_medium_risk_sends_approval(self, tmp_path):
        orch, sender = build(tmp_path, agent1=lambda req, ctx: [{"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x"}, "risk": "medium"}])
        outcome = run(handlers.handle_telegram_message(orch, sender, 111, "save a file"))
        assert outcome["status"] == "awaiting_approval_1"
        assert len(sender.approvals) == 1
        user, text, kb = sender.approvals[0]
        assert user == 111
        assert "Approval #1" in text
        labels = [b.text for row in kb.inline_keyboard for b in row]
        assert labels == ["APPROVE", "DISAPPROVE"]

    def test_low_risk_auto_proceed_dispatches(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, sender = build(tmp_path, agent1=lambda req, ctx: [{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}], dispatcher=dispatcher)
        orch.settings.auto_proceed_low_risk = False
        orch.sessions.get_or_create(111).auto_proceed_low_risk = True
        outcome = run(handlers.handle_telegram_message(orch, sender, 111, "screenshot"))
        assert outcome["status"] == "dispatched"
        assert dispatcher.calls
        assert sender.messages and "auto-proceeded" in sender.messages[-1][1]

    def test_unauthorized_silently_dropped(self, tmp_path):
        orch, sender = build(tmp_path)
        outcome = run(handlers.handle_telegram_message(orch, sender, 999, "delete everything"))
        assert outcome is None
        assert sender.messages == [] and sender.approvals == []

    def test_agent1_error_sends_message(self, tmp_path):
        def bad_agent(req, ctx):
            raise LLMValidationError("could not parse")

        orch, sender = build(tmp_path, agent1=bad_agent)
        run(handlers.handle_telegram_message(orch, sender, 111, "do something"))
        assert sender.messages and "could not parse" in sender.messages[-1][1]


class TestCallbackRouting:
    def test_approve_1_dispatches(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, sender = build(tmp_path, agent1=lambda req, ctx: [{"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x"}, "risk": "medium"}], dispatcher=dispatcher)
        rid = run(handlers.handle_telegram_message(orch, sender, 111, "save"))["request_id"]
        outcome = run(handlers.handle_callback(orch, sender, 111, f"approve1:{rid}"))
        assert outcome["status"] == "dispatched"
        assert dispatcher.calls and dispatcher.calls[0][1] == rid
        assert any("dispatched" in text for _, text in sender.messages)

    def test_disapprove_1_stops(self, tmp_path):
        orch, sender = build(tmp_path, agent1=lambda req, ctx: [{"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x"}, "risk": "medium"}])
        rid = run(handlers.handle_telegram_message(orch, sender, 111, "save"))["request_id"]
        outcome = run(handlers.handle_callback(orch, sender, 111, f"disapprove1:{rid}"))
        assert outcome["status"] == "stopped"
        assert any("Cancelled" in text for _, text in sender.messages)

    def test_execute_2_flows(self, tmp_path):
        orch, sender = build(tmp_path)
        plan = ["cd /tmp", "pwd"]
        orch.handle_agent2_plan("rid", plan, 111)
        outcome = run(handlers.handle_callback(orch, sender, 111, "execute2:rid"))
        assert outcome["status"] == "executing"

    def test_cancel_2_stops(self, tmp_path):
        orch, sender = build(tmp_path)
        orch.handle_agent2_plan("rid", ["cd /tmp"], 111)
        outcome = run(handlers.handle_callback(orch, sender, 111, "cancel2:rid"))
        assert outcome["status"] == "stopped"

    def test_unknown_request_answered(self, tmp_path):
        orch, sender = build(tmp_path)
        run(handlers.handle_callback(orch, sender, 111, "approve1:nonexistent"))
        assert sender.messages and "No pending approval" in sender.messages[-1][1]

    def test_unauthorized_callback_dropped(self, tmp_path):
        orch, sender = build(tmp_path)
        orch.handle_agent2_plan("rid", ["cd"], 111)
        outcome = run(handlers.handle_callback(orch, sender, 999, "execute2:rid"))
        assert outcome is None
        assert sender.messages == []

    def test_garbage_callback_ignored(self, tmp_path):
        orch, sender = build(tmp_path)
        outcome = run(handlers.handle_callback(orch, sender, 111, "garbage"))
        assert outcome is None


class TestRelayRouting:
    def test_execution_result_updates_session_and_notifies(self, tmp_path):
        orch, sender = build(tmp_path)
        orch.handle_request(111, "go to backend")
        rid = "made-up"

        result = {"type": "EXECUTION_RESULT", "request_id": rid, "user_id": 111, "status": "ok", "cwd": "/home/u/backend", "results": [{"name": "cd", "status": "ok", "output": ""}]}
        outcome = run(handlers.handle_relay_message(orch, sender, result))
        assert outcome["status"] == "recorded"
        assert sender.messages and any("/home/u/backend" in text for _, text in sender.messages)
        session = orch.sessions.get(111)
        assert session.cwd == "/home/u/backend"

    def test_relay_error_notifies_user(self, tmp_path):
        orch, sender = build(tmp_path)
        outcome = run(handlers.handle_relay_message(orch, sender, {"type": "ERROR", "request_id": "x", "user_id": 111, "error": "allow-list blocked"}))
        assert outcome == {"status": "error_to_user", "error": "allow-list blocked"}
        assert sender.messages and "allow-list blocked" in sender.messages[-1][1]