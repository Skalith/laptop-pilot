from shared.messages import EventType
from agent1.agent import Agent1
from agent1.tests.test_agent1 import FakeLLM
from shared.llm.failover import FallbackRouter
from orchestrator.approvals import ApprovalStore
from orchestrator.audit import AuditLogger
from orchestrator.config import Settings
from orchestrator.pipeline import Orchestrator
from orchestrator.tests.test_approvals import FakeClock


class FakeAgent1:
    def __init__(self, result=None, error=None):
        default = [
            {"action": "CHANGE_DIRECTORY", "parameters": {"path": "~/projects"}, "risk": "low"},
            {"action": "OPEN_APPLICATION", "parameters": {"application": "vscode"}, "risk": "low"},
        ]
        self.result = default if result is None else result
        self.error = error
        self.requests: list[str] = []
        self.contexts: list[dict] = []

    def __call__(self, request, context):
        self.requests.append(request)
        self.contexts.append(context)
        if self.error:
            raise self.error
        return self.result


class FakeDispatcher:
    def __init__(self, error=None):
        self.calls: list[tuple[list, str]] = []
        self.error = error

    def __call__(self, commands, request_id):
        if self.error:
            raise self.error
        self.calls.append((commands, request_id))


MEDIUM_CMD = {"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": "~/x.txt"}, "risk": "medium"}
HIGH_CMD = {"action": "RUN_COMMAND", "parameters": {"command": "rm -rf /tmp/x"}, "risk": "high"}

PLAN = ["check", "launch code ~/x", "wait for window"]


def build_orchestrator(tmp_path, *, agent1=None, dispatcher=None, execute_signal=None, auto_proceed=False, time_func=None):
    settings = Settings(
        authorized_user_ids={111},
        relay_secret="s",
        relay_url="ws://x",
        log_path=str(tmp_path / "audit.log"),
        auto_proceed_low_risk=auto_proceed,
    )
    clock = FakeClock()
    approvals = ApprovalStore(180, clock=clock)
    audit = AuditLogger(settings.log_path)
    return Orchestrator(
        settings,
        approvals=approvals,
        audit=audit,
        agent1=agent1,
        dispatcher=dispatcher,
        execute_signal=execute_signal,
        time_func=time_func,
    ), clock


class TestAuthorization:
    def test_unauthorized_sender_rejected_and_logged(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path)
        result = orch.handle_request(999, "delete everything")
        assert result["status"] == "rejected"
        lines = orch.audit.read()
        assert any("REJECTED unauthorized" in line for line in lines)


class TestRequestFlow:
    def test_medium_risk_waits_for_approval_1(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]))
        result = orch.handle_request(111, "save my file")
        assert result["status"] == "awaiting_approval_1"
        assert result["risk"] == "medium"
        rid = result["request_id"]
        assert orch.approvals.get(rid) is not None
        events = [line.split("] [")[1] for line in orch.audit.read()]
        assert EventType.REQUEST_RECEIVED in events
        assert EventType.COMMAND_GENERATED in events
        assert EventType.APPROVAL_1_SENT in events

    def test_low_risk_without_auto_proceed_waits_for_approval_1(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1())
        result = orch.handle_request(111, "open vscode")
        assert result["status"] == "awaiting_approval_1"
        assert result["risk"] == "low"


class TestApproval1:
    def test_approve_dispatches_and_logs(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]), dispatcher=dispatcher)
        result = orch.handle_request(111, "save it")
        rid = result["request_id"]

        outcome = orch.handle_approval_1(rid, "approve", 111)
        assert outcome["status"] == "dispatched"
        assert dispatcher.calls[0][0] == [MEDIUM_CMD]
        assert dispatcher.calls[0][1] == rid
        events = " ".join(orch.audit.read())
        assert "approved" in events
        assert EventType.COMMAND_DISPATCHED in events

    def test_disapprove_stops_without_dispatch(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]), dispatcher=dispatcher)
        rid = orch.handle_request(111, "save it")["request_id"]

        outcome = orch.handle_approval_1(rid, "disapprove", 111)
        assert outcome["status"] == "stopped"
        assert dispatcher.calls == []
        assert "disapproved" in " ".join(orch.audit.read())

    def test_approval_unknown_request_id(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path)
        outcome = orch.handle_approval_1("nope", "approve", 111)
        assert outcome["status"] == "not_found"


class TestAutoProceed:
    def test_low_risk_auto_proceeds(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1(), dispatcher=dispatcher, auto_proceed=True)
        result = orch.handle_request(111, "open vscode")
        assert result["status"] == "dispatched"
        assert result["auto_proceeded"] is True
        assert len(dispatcher.calls) == 1
        assert orch.approvals.pending_count() == 0

    def test_high_risk_never_auto_proceeds(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([HIGH_CMD]), dispatcher=dispatcher, auto_proceed=True)
        result = orch.handle_request(111, "rm -rf")
        assert result["status"] == "awaiting_approval_1"
        assert dispatcher.calls == []


class TestAgent1Failures:
    def test_agent1_raises_returns_error_logs_error(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1(error=RuntimeError("api down")), dispatcher=dispatcher)
        result = orch.handle_request(111, "do a thing")
        assert result["status"] == "error"
        assert "api down" in result["error"]
        assert dispatcher.calls == []
        assert any(EventType.ERROR in line for line in orch.audit.read())

    def test_agent1_empty_list_returns_error(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1(result=[]))
        result = orch.handle_request(111, "nothing")
        assert result["status"] == "error"
        assert orch.approvals.pending_count() == 0


class BrokenProvider:
    @property
    def name(self) -> str:
        return "broken"

    def generate_json(self, *, system, user, max_tokens=1024):
        raise OSError("upstream 503")


class NamedLLM:
    """Gives FakeLLM the name LLMProvider requires for routing."""

    def __init__(self, name, payloads):
        self._name = name
        self.llm = FakeLLM(payloads)

    @property
    def name(self) -> str:
        return self._name

    def generate_json(self, *, system, user, max_tokens=1024):
        return self.llm.generate_json(system=system, user=user, max_tokens=max_tokens)


class TestAllProvidersDown:
    def test_real_agent1_all_providers_down_errors_without_approval(self, tmp_path):
        router = FallbackRouter([BrokenProvider(), BrokenProvider()])
        orch, _ = build_orchestrator(tmp_path, agent1=Agent1(router))
        result = orch.handle_request(111, "do something")
        assert result["status"] == "error"
        assert "503" in result["error"]
        assert orch.approvals.pending_count() == 0
        assert any(EventType.ERROR in line and "agent1" in line for line in orch.audit.read())

    def test_real_agent1_failover_to_backup_provider(self, tmp_path):
        from agent1.tests.test_agent1 import VALID_PAYLOAD

        router = FallbackRouter([BrokenProvider(), NamedLLM("backup", [VALID_PAYLOAD])])
        orch, _ = build_orchestrator(tmp_path, agent1=Agent1(router))
        result = orch.handle_request(111, "open vscode")
        assert result["status"] == "awaiting_approval_1"
        assert result["risk"] == "low"
        assert router.last_served == "backup"


class TestTTLExpiry:
    def test_expired_approval_is_auto_cancelled_and_logged(self, tmp_path):
        orch, clock = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]))
        rid = orch.handle_request(111, "save it")["request_id"]
        assert orch.approvals.pending_count() == 1

        clock.advance(181)
        expired = orch.sweep_expired_approvals()
        assert expired == [rid]
        assert orch.approvals.pending_count() == 0
        assert any(EventType.APPROVAL_EXPIRED in line and rid in line for line in orch.audit.read())

        # resolving the expired approval is a no-op
        assert orch.handle_approval_1(rid, "approve", 111)["status"] == "not_found"

    def test_not_yet_expired_not_cancelled(self, tmp_path):
        orch, clock = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]))
        rid = orch.handle_request(111, "save")["request_id"]
        clock.advance(179)
        assert orch.sweep_expired_approvals() == []
        assert orch.approvals.get(rid) is not None


class TestDispatcherFailures:
    def test_dispatcher_error_is_logged_not_crashed(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]), dispatcher=FakeDispatcher(error=RuntimeError("relay down")))
        rid = orch.handle_request(111, "save")["request_id"]
        outcome = orch.handle_approval_1(rid, "approve", 111)
        assert outcome["status"] == "dispatched"
        assert any("dispatch failed" in line for line in orch.audit.read())

    def test_agent2_offline_connection_error_logged(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]), dispatcher=FakeDispatcher(error=ConnectionError("agent2 offline")))
        rid = orch.handle_request(111, "save")["request_id"]
        orch.handle_approval_1(rid, "approve", 111)
        lines = [line for line in orch.audit.read() if "dispatch failed" in line]
        assert any("agent2 offline" in line for line in lines)
        assert orch.approvals.pending_count() == 0


class TestAgent2Timeout:
    class WallClock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, seconds):
            self.t += seconds

    def _dispatch_a_request(self, tmp_path, dispatcher):
        clock = self.WallClock()
        orch, _ = build_orchestrator(tmp_path, agent1=FakeAgent1([MEDIUM_CMD]), dispatcher=dispatcher, time_func=clock)
        rid = orch.handle_request(111, "save")["request_id"]
        orch.handle_approval_1(rid, "approve", 111)
        return orch, rid, clock

    def test_stale_dispatch_is_detected_after_timeout(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, rid, clock = self._dispatch_a_request(tmp_path, dispatcher)
        assert orch.sweep_stale_dispatches() == []
        clock.advance(61)
        assert orch.sweep_stale_dispatches() == [rid]
        assert any("did not respond within" in line and rid in line for line in orch.audit.read())

    def test_plan_response_clears_inflight(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, rid, clock = self._dispatch_a_request(tmp_path, dispatcher)
        orch.handle_agent2_plan(rid, PLAN, 111)
        clock.advance(1000)
        assert orch.sweep_stale_dispatches() == []

    def test_result_response_clears_inflight(self, tmp_path):
        dispatcher = FakeDispatcher()
        orch, rid, clock = self._dispatch_a_request(tmp_path, dispatcher)
        orch.handle_agent2_result(rid, {"request_id": rid, "status": "ok"})
        clock.advance(1000)
        assert orch.sweep_stale_dispatches() == []


class FakeExecuteSignal:
    def __init__(self, error=None):
        self.signalled: list[str] = []
        self.error = error

    def __call__(self, request_id):
        if self.error:
            raise self.error
        self.signalled.append(request_id)


class TestApproval2Flow:
    def test_plan_creates_approval_2_and_logs(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path)
        result = orch.handle_agent2_plan("r1", PLAN, 111)
        assert result["status"] == "awaiting_approval_2"
        assert orch.approvals.get("r1").kind == "approval_2"
        assert any("APPROVAL_2_SENT" in line and "r1" in line for line in orch.audit.read())

    def test_execute_signals_agent2(self, tmp_path):
        signals = FakeExecuteSignal()
        orch, _ = build_orchestrator(tmp_path, execute_signal=signals)
        orch.handle_agent2_plan("r1", PLAN, 111)
        outcome = orch.handle_approval_2("r1", "execute", 111)
        assert outcome["status"] == "executing"
        assert signals.signalled == ["r1"]
        assert any("APPROVAL_2_RESULT" in line and "execute" in line for line in orch.audit.read())

    def test_execute_signal_error_is_logged_not_crashed(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path, execute_signal=FakeExecuteSignal(error=RuntimeError("relay lost")))
        orch.handle_agent2_plan("r1", PLAN, 111)
        outcome = orch.handle_approval_2("r1", "execute", 111)
        assert outcome["status"] == "executing"
        assert any("execute signal failed" in line and "relay lost" in line for line in orch.audit.read())

    def test_execute_unknown_request_is_not_found(self, tmp_path):
        signals = FakeExecuteSignal()
        orch, _ = build_orchestrator(tmp_path, execute_signal=signals)
        assert orch.handle_approval_2("nope", "execute", 111)["status"] == "not_found"
        assert signals.signalled == []

    def test_cancel_stops_without_signal(self, tmp_path):
        signals = FakeExecuteSignal()
        orch, _ = build_orchestrator(tmp_path, execute_signal=signals)
        orch.handle_agent2_plan("r1", PLAN, 111)
        outcome = orch.handle_approval_2("r1", "cancel", 111)
        assert outcome["status"] == "stopped"
        assert signals.signalled == []

    def test_approval_2_expiry_cancelled(self, tmp_path):
        orch, clock = build_orchestrator(tmp_path)
        rid = orch.handle_agent2_plan("r1", PLAN, 111)["request_id"]
        clock.advance(181)
        assert orch.sweep_expired_approvals() == [rid]
        assert orch.handle_approval_2(rid, "execute", 111)["status"] == "not_found"
        assert any("APPROVAL_EXPIRED" in line for line in orch.audit.read())


class TestResultRecording:
    def test_result_recorded_and_session_updated(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path)
        rid = orch.handle_request(111, "go to backend")["request_id"]
        session = orch.sessions.get(111)

        orch.handle_agent2_result(
            rid,
            {"request_id": rid, "cwd": "/home/u/backend", "state": {"windows": ["vscode"]}},
        )

        assert any("EXECUTION_RESULT" in line for line in orch.audit.read())
        assert session.cwd == "/home/u/backend"
        assert session.last_laptop_state == {"windows": ["vscode"]}
        assert len(session.history) == 1

    def test_result_without_cwd_keeps_session(self, tmp_path):
        orch, _ = build_orchestrator(tmp_path)
        orch.handle_request(111, "hi")
        session = orch.sessions.get(111)
        orch.handle_agent2_result("rid", {"request_id": "rid", "state": None})
        assert session.cwd == "~/"