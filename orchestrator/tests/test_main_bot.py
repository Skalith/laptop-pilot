from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.config import Settings
from orchestrator.main import create_app

MEDIUM_CMD = {"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x.txt"}, "risk": "medium"}


class FakeSender:
    def __init__(self):
        self.messages: list[tuple[int, str]] = []
        self.approvals: list[tuple[int, str, object]] = []

    async def send_message(self, user_id, text):
        self.messages.append((user_id, text))

    async def send_approval(self, user_id, text, keyboard):
        self.approvals.append((user_id, text, keyboard))


def build_client(tmp_path, *, agent1=None, create_sender=True):
    settings = Settings(
        authorized_user_ids={111},
        relay_secret="s",
        relay_url="ws://x",
        log_path=str(tmp_path / "audit.log"),
    )
    sender = FakeSender() if create_sender else None
    app = create_app(settings, agent1=agent1, sender=sender)
    return app, app.state.orchestrator, sender


class TestWebhookMessages:
    def test_message_triggers_approval_keyboard(self, tmp_path):
        app, orch, sender = build_client(tmp_path, agent1=lambda req, ctx: [MEDIUM_CMD])
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"message": {"from": {"id": 111}, "text": "save it"}})
        assert resp.json()["status"] == "ok"
        assert len(sender.approvals) == 1
        assert sender.approvals[0][0] == 111

    def test_unauthorized_message_silently_dropped(self, tmp_path):
        app, orch, sender = build_client(tmp_path)
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"message": {"from": {"id": 999}, "text": "delete"}})
        assert resp.json()["status"] == "ok"
        assert sender.messages == [] and sender.approvals == []


class TestWebhookCallbacks:
    def _approve_flow(self, tmp_path):
        app, orch, sender = build_client(tmp_path, agent1=lambda req, ctx: [MEDIUM_CMD])
        with TestClient(app) as client:
            client.post("/telegram/webhook", json={"message": {"from": {"id": 111}, "text": "save"}})
            rid = orch.approvals.pending_ids()[0]
            resp = client.post(
                "/telegram/webhook",
                json={"callback_query": {"from": {"id": 111}, "data": f"approve1:{rid}"}},
            )
        return resp, orch, sender, rid

    def test_approve_callback_dispatches(self, tmp_path):
        resp, orch, sender, rid = self._approve_flow(tmp_path)
        assert resp.json()["status"] == "ok"
        assert any("dispatched" in text for _, text in sender.messages)

    def test_ignore_non_message_update(self, tmp_path):
        app, orch, sender = build_client(tmp_path)
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"update_id": 1})
        assert resp.json()["status"] == "ignored"


class TestHealth:
    def test_health_reflects_pending(self, tmp_path):
        app, orch, sender = build_client(tmp_path, agent1=lambda req, ctx: [MEDIUM_CMD])
        with TestClient(app) as client:
            before = client.get("/health").json()
            client.post("/telegram/webhook", json={"message": {"from": {"id": 111}, "text": "save"}})
            after = client.get("/health").json()
        assert before["pending_approvals"] == 0
        assert after["pending_approvals"] == 1