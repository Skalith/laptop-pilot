from __future__ import annotations

import json
import os

os.environ.setdefault("RELAY_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from relay.main import app

AUTH_QS = {"token": "test-secret"}
DENY_QS = {"token": "wrong"}
PAYLOAD = {"type": "DISPATCH_COMMAND", "request_id": "r1", "payload": {"action": "TAKE_SCREENSHOT"}}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_peers_report_offline_when_none_connected(self, client):
        data = client.get("/health").json()
        assert data["peers"] == {"orchestrator": False, "agent2": False}


class TestRouting:
    def test_orchestrator_to_agent2(self, client):
        with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
            with client.websocket_connect("/ws/agent2", params=AUTH_QS) as ag2:
                orch.send_text(json.dumps(PAYLOAD))
                received = json.loads(ag2.receive_text())
        assert received == PAYLOAD

    def test_agent2_to_orchestrator(self, client):
        with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
            with client.websocket_connect("/ws/agent2", params=AUTH_QS) as ag2:
                ag2.send_text(json.dumps({"type": "EXECUTION_RESULT", "request_id": "r1"}))
                received = json.loads(orch.receive_text())
        assert received["type"] == "EXECUTION_RESULT"

    def test_no_echo_back_to_sender(self, client):
        with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
            with client.websocket_connect("/ws/agent2", params=AUTH_QS) as ag2:
                orch.send_text(json.dumps(PAYLOAD))
                assert json.loads(ag2.receive_text()) == PAYLOAD
                ag2.send_text(json.dumps({"type": "EXECUTION_RESULT", "request_id": "r1"}))
                # the first thing the sender sees is the reply, not an echo
                assert json.loads(orch.receive_text())["type"] == "EXECUTION_RESULT"

    def test_target_offline_returns_error_to_sender(self, client):
        with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
            orch.send_text(json.dumps(PAYLOAD))
            msg = json.loads(orch.receive_text())
        assert msg["type"] == "ERROR"
        assert msg["error"] == "target_not_online"

    def test_invalid_json_returns_error_to_sender(self, client):
        with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
            orch.send_text("this is {not json")
            msg = json.loads(orch.receive_text())
        assert msg["type"] == "ERROR"
        assert msg["error"] == "invalid_json"


class TestAuth:
    def test_unauthorized_orchestrator_rejected(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/orchestrator", params=DENY_QS) as _:
                pass

    def test_unauthorized_agent2_rejected(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/agent2", params=DENY_QS) as _:
                pass

    def test_missing_token_rejected(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/orchestrator") as _:
                pass

    def test_rejecting_one_peer_does_not_affect_the_other(self, client):
        # a rejected rogue orchestrator must not disrupt an already-connected agent2
        with client.websocket_connect("/ws/agent2", params=AUTH_QS) as ag2:
            with pytest.raises(Exception):
                with client.websocket_connect("/ws/orchestrator", params=DENY_QS) as _:
                    pass
            with client.websocket_connect("/ws/orchestrator", params=AUTH_QS) as orch:
                orch.send_text(json.dumps(PAYLOAD))
                assert json.loads(ag2.receive_text()) == PAYLOAD