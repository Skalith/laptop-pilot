from fastapi.testclient import TestClient

from orchestrator.config import Settings
from orchestrator.main import create_app

MEDIUM_CMD = {"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x.txt"}, "risk": "medium"}


def build_client(tmp_path, *, agent1=None, dispatcher=None):
    settings = Settings(
        authorized_user_ids={111},
        relay_secret="s",
        relay_url="ws://x",
        log_path=str(tmp_path / "audit.log"),
    )
    app = create_app(settings, agent1=agent1, dispatcher=dispatcher)
    return app, app.state.orchestrator


class TestHealth:
    def test_health(self, tmp_path):
        app, orch = build_client(tmp_path)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            assert resp.json()["pending_approvals"] == 0


class TestWebhook:
    def test_authorized_user_proceeds_to_approval(self, tmp_path):
        app, orch = build_client(tmp_path, agent1=lambda req, ctx: [MEDIUM_CMD])
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"message": {"from": {"id": 111}, "text": "save it"}})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert orch.approvals.pending_count() == 1

    def test_unauthorized_user_silently_dropped(self, tmp_path):
        app, orch = build_client(tmp_path)
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"message": {"from": {"id": 999}, "text": "delete"}})
        assert resp.json()["status"] == "ok"
        assert orch.approvals.pending_count() == 0

    def test_ignored_when_no_message(self, tmp_path):
        app, orch = build_client(tmp_path)
        with TestClient(app) as client:
            resp = client.post("/telegram/webhook", json={"update_id": 1})
        assert resp.json()["status"] == "ignored"