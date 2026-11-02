from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import threading
import time

os.environ.setdefault("RELAY_SECRET", "test-secret")

import pytest
import uvicorn

from relay.main import app
from shared.messages import EventType, MessageType, envelope
from shared.net import RelayClient
from shared.llm.failover import FallbackRouter

from agent1.agent import Agent1
from agent2.allowlist import AllowList
from agent2.config import Agent2Config
from agent2.executor import Executor
from agent2.service import Agent2

from orchestrator.config import Settings
from orchestrator.pipeline import Orchestrator

ACTIONS = ["TAKE_SCREENSHOT", "FILE_OPERATION", "CHANGE_DIRECTORY", "RUN_COMMAND"]
USER_ID = 111


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def relay_url() -> str:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    yield f"ws://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


class FakeLLM:
    """Canned payloads for Agent 1 (goes through the real Agent1 class)."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, *, system, user, max_tokens=1024):
        self.calls.append((system, user))
        if not self.payloads:
            raise RuntimeError("no payload queued")
        return self.payloads.pop(0)


class FakeProvider:
    """LLMProvider with a stable name (usable inside the real FallbackRouter)."""

    def __init__(self, name, payloads):
        self._name = name
        self.payloads = list(payloads)
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate_json(self, *, system, user, max_tokens=1024):
        self.calls += 1
        if not self.payloads:
            raise OSError(f"{self._name} out of payloads")
        return self.payloads.pop(0)


class Harness:
    """Full chain: orchestrator <-> relay <-> agent2, driven scenario by scenario."""

    def __init__(self, relay_url: str, workdir: str, *, auto_proceed: bool, agent_payloads: list[dict]):
        self.workdir = workdir
        self.plans: asyncio.Queue = asyncio.Queue()
        self.results: asyncio.Queue = asyncio.Queue()
        self.errors: asyncio.Queue = asyncio.Queue()
        self.orch: Orchestrator | None = None
        self.orch_ws: RelayClient = RelayClient(
            relay_url, "test-secret", path="/ws/orchestrator", on_message=self._on_orch_message
        )

        settings = Settings(
            authorized_user_ids={USER_ID},
            relay_secret="test-secret",
            relay_url=relay_url,
            log_path=os.path.join(workdir, "audit.log"),
            auto_proceed_low_risk=auto_proceed,
        )
        self.orch = Orchestrator(
            settings,
            agent1=Agent1(FakeLLM(agent_payloads)),
            dispatcher=self._dispatcher,
            execute_signal=self._execute_signal,
        )

        allow = AllowList(
            actions=ACTIONS,
            paths=None,
            commands=None,
            applications=None,
        )
        agent_config = Agent2Config(relay_url=relay_url, relay_secret="test-secret")
        self.agent2 = Agent2(agent_config, allowlist=allow, executor=Executor())

    async def _on_orch_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == MessageType.APPROVAL_2_PLAN:
            self.orch.handle_agent2_plan(message["request_id"], message.get("plan"), message.get("user_id") or USER_ID)
            await self.plans.put(message)
        elif message_type == MessageType.EXECUTION_RESULT:
            self.orch.handle_agent2_result(message["request_id"], message)
            await self.results.put(message)
        elif message_type == MessageType.ERROR:
            await self.errors.put(message)

    def _dispatcher(self, commands: list[dict], request_id: str) -> None:
        asyncio.get_running_loop().create_task(
            self.orch_ws.publish(
                envelope(MessageType.DISPATCH_COMMAND, request_id=request_id, user_id=USER_ID, commands=commands)
            )
        )

    def _execute_signal(self, request_id: str) -> None:
        asyncio.get_running_loop().create_task(
            self.orch_ws.publish(envelope(MessageType.EXECUTE_SIGNAL, request_id=request_id))
        )

    def _delete_target(self, name: str) -> str:
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("do not delete")
        return path

    async def start(self) -> None:
        await self.orch_ws.connect()
        self.orch_task = asyncio.create_task(self.orch_ws.run())
        self.agent2_task = asyncio.create_task(self.agent2.run())
        await asyncio.sleep(0.4)

    async def stop(self) -> None:
        self.agent2_task.cancel()
        self.orch_task.cancel()
        await asyncio.gather(self.agent2_task, self.orch_task, return_exceptions=True)
        await self.orch_ws.close()
        self.agent2.executor.shell.close()

    async def wait_plan(self, request_id: str, timeout: float = 10.0) -> dict:
        while True:
            plan = await asyncio.wait_for(self.plans.get(), timeout=timeout)
            if plan["request_id"] == request_id:
                return plan

    async def wait_result(self, request_id: str, timeout: float = 10.0) -> dict:
        while True:
            result = await asyncio.wait_for(self.results.get(), timeout=timeout)
            if result["request_id"] == request_id:
                return result

    async def assert_no_plan(self, request_id: str, window: float = 0.8) -> None:
        try:
            plan = await asyncio.wait_for(self.plans.get(), timeout=window)
        except asyncio.TimeoutError:
            return
        raise AssertionError(f"unexpected plan for {request_id}: {plan}")

    def audit_lines(self) -> list[str]:
        return self.orch.audit.read()

    def _audit_index(self, marker: str) -> int:
        lines = self.audit_lines()
        for index, line in enumerate(lines):
            if marker in line:
                return index
        raise AssertionError(f"audit marker {marker!r} not found in {lines}")

    def assert_ordered(self, *markers: str) -> None:
        positions = [self._audit_index(marker) for marker in markers]
        assert positions == sorted(positions), f"audit ordering violated: {markers} at {positions}"


SCREENSHOT_PAYLOAD = {"commands": [{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}]}


async def _flow_low_risk_auto_proceed(relay_url: str, workdir: str) -> None:
    """Low risk + auto-proceed: single dispatch, plan, then explicit EXECUTE (Approval #2)."""
    harness = Harness(relay_url, workdir, auto_proceed=True, agent_payloads=[SCREENSHOT_PAYLOAD])
    try:
        await harness.start()
        outcome = harness.orch.handle_request(USER_ID, "take a screenshot")
        assert outcome["status"] == "dispatched"
        assert outcome["auto_proceeded"] is True
        request_id = outcome["request_id"]

        plan = await harness.wait_plan(request_id)
        assert plan["plan"]
        assert harness.orch.handle_approval_2(request_id, "execute", USER_ID)["status"] == "executing"

        result = await harness.wait_result(request_id)
        assert result["status"] == "ok"
        assert result["results"][0]["mime"] == "image/png"

        session = harness.orch.sessions.get(USER_ID)
        assert session.history[-1]["result"]["status"] == "ok"
        harness.assert_ordered(
            EventType.REQUEST_RECEIVED,
            EventType.COMMAND_GENERATED,
            EventType.COMMAND_DISPATCHED,
            EventType.APPROVAL_2_SENT,
            EventType.APPROVAL_2_RESULT,
            EventType.EXECUTION_RESULT,
        )
    finally:
        await harness.stop()


DELETE_PAYLOAD_BASE = {"commands": [{"action": "FILE_OPERATION", "parameters": {"operation": "delete", "path": "PATH"}, "risk": "high"}]}


async def _flow_high_risk_double_approval(relay_url: str, workdir: str) -> None:
    """High risk: Approval #1 approve -> dispatch -> plan -> Approval #2 execute -> file gone."""
    target = os.path.join(workdir, "victim.txt")
    payload = dict(DELETE_PAYLOAD_BASE)
    payload["commands"] = [dict(payload["commands"][0], parameters={"operation": "delete", "path": target})]
    harness = Harness(relay_url, workdir, auto_proceed=False, agent_payloads=[payload])
    try:
        await harness.start()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("do not delete")

        outcome = harness.orch.handle_request(USER_ID, "delete victim.txt")
        assert outcome["status"] == "awaiting_approval_1"
        assert outcome["risk"] == "high"
        request_id = outcome["request_id"]

        assert harness.orch.handle_approval_1(request_id, "approve", USER_ID)["status"] == "dispatched"
        plan = await harness.wait_plan(request_id)
        assert plan["plan"]
        assert harness.orch.handle_approval_2(request_id, "execute", USER_ID)["status"] == "executing"

        result = await harness.wait_result(request_id)
        assert result["status"] == "ok"
        assert not os.path.exists(target)

        session = harness.orch.sessions.get(USER_ID)
        assert session.history[-1]["result"]["status"] == "ok"
        harness.assert_ordered(
            EventType.APPROVAL_1_SENT,
            EventType.APPROVAL_1_RESULT,
            EventType.COMMAND_DISPATCHED,
            EventType.APPROVAL_2_SENT,
            EventType.APPROVAL_2_RESULT,
            EventType.EXECUTION_RESULT,
        )
    finally:
        await harness.stop()


async def _flow_disapproved_at_approval_1(relay_url: str, workdir: str) -> None:
    """Disapprove at Approval #1: nothing dispatched, nothing executed."""
    target = os.path.join(workdir, "safe.txt")
    payload = dict(DELETE_PAYLOAD_BASE)
    payload["commands"] = [dict(payload["commands"][0], parameters={"operation": "delete", "path": target})]
    harness = Harness(relay_url, workdir, auto_proceed=False, agent_payloads=[payload])
    try:
        await harness.start()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("keep me")

        outcome = harness.orch.handle_request(USER_ID, "delete safe.txt")
        assert outcome["status"] == "awaiting_approval_1"
        request_id = outcome["request_id"]

        assert harness.orch.handle_approval_1(request_id, "disapprove", USER_ID)["status"] == "stopped"
        await harness.assert_no_plan(request_id)
        assert os.path.exists(target)
        harness.assert_ordered(EventType.APPROVAL_1_SENT, EventType.APPROVAL_1_RESULT)
        assert "disapproved" in harness.audit_lines()[-1]
    finally:
        await harness.stop()


async def _flow_cancelled_at_approval_2(relay_url: str, workdir: str) -> None:
    """Cancel at Approval #2: no EXECUTE sent, file survives."""
    target = os.path.join(workdir, "keep.txt")
    payload = dict(DELETE_PAYLOAD_BASE)
    payload["commands"] = [dict(payload["commands"][0], parameters={"operation": "delete", "path": target})]
    harness = Harness(relay_url, workdir, auto_proceed=False, agent_payloads=[payload])
    try:
        await harness.start()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("keep me")

        outcome = harness.orch.handle_request(USER_ID, "delete keep.txt")
        request_id = outcome["request_id"]
        assert harness.orch.handle_approval_1(request_id, "approve", USER_ID)["status"] == "dispatched"
        await harness.wait_plan(request_id)

        assert harness.orch.handle_approval_2(request_id, "cancel", USER_ID)["status"] == "stopped"
        try:
            await asyncio.wait_for(harness.results.get(), timeout=0.8)
            raise AssertionError("expected no EXECUTION_RESULT for cancelled request")
        except asyncio.TimeoutError:
            pass
        assert os.path.exists(target)
        harness.assert_ordered(EventType.APPROVAL_2_SENT, EventType.APPROVAL_2_RESULT)
    finally:
        await harness.stop()


async def _flow_failover(relay_url: str, workdir: str) -> None:
    """Primary provider down -> FallbackRouter switches to backup; full chain completes."""
    switches: list[tuple[str, str]] = []

    def on_switch(failed_provider: str, error: Exception) -> None:
        switches.append((failed_provider, str(error)))

    router = FallbackRouter(
        [
            FakeProvider("broken", []),
            FakeProvider("backup", [SCREENSHOT_PAYLOAD]),
        ],
        on_switch=on_switch,
    )

    settings = Settings(
        authorized_user_ids={USER_ID},
        relay_secret="test-secret",
        relay_url=relay_url,
        log_path=os.path.join(workdir, "audit.log"),
        auto_proceed_low_risk=True,
    )

    results: asyncio.Queue = asyncio.Queue()
    plans: asyncio.Queue = asyncio.Queue()

    async def on_orch_message(message: dict) -> None:
        if message.get("type") == MessageType.APPROVAL_2_PLAN:
            orch.handle_agent2_plan(message["request_id"], message.get("plan"), message.get("user_id") or USER_ID)
            await plans.put(message)
        elif message.get("type") == MessageType.EXECUTION_RESULT:
            orch.handle_agent2_result(message["request_id"], message)
            await results.put(message)

    orch_ws = RelayClient(relay_url, "test-secret", path="/ws/orchestrator", on_message=on_orch_message)

    def dispatcher(commands: list[dict], request_id: str) -> None:
        asyncio.get_running_loop().create_task(
            orch_ws.publish(envelope(MessageType.DISPATCH_COMMAND, request_id=request_id, user_id=USER_ID, commands=commands))
        )

    def execute_signal(request_id: str) -> None:
        asyncio.get_running_loop().create_task(orch_ws.publish(envelope(MessageType.EXECUTE_SIGNAL, request_id=request_id)))

    orch = Orchestrator(settings, agent1=Agent1(router), dispatcher=dispatcher, execute_signal=execute_signal)

    allow = AllowList(actions=ACTIONS, paths=None, commands=None, applications=None)
    agent_config = Agent2Config(relay_url=relay_url, relay_secret="test-secret")
    service = Agent2(agent_config, allowlist=allow, executor=Executor())

    await orch_ws.connect()
    orch_task = asyncio.create_task(orch_ws.run())
    agent2_task = asyncio.create_task(service.run())
    try:
        await asyncio.sleep(0.4)
        outcome = orch.handle_request(USER_ID, "retry after outage")
        assert outcome["status"] == "dispatched"
        request_id = outcome["request_id"]
        plan = await asyncio.wait_for(plans.get(), timeout=10.0)
        assert plan["request_id"] == request_id
        assert orch.handle_approval_2(request_id, "execute", USER_ID)["status"] == "executing"
        result = await asyncio.wait_for(results.get(), timeout=10.0)
        assert result["status"] == "ok"
        assert result["results"][0]["mime"] == "image/png"
        assert switches == [("broken", "broken out of payloads")]
        assert router.last_served == "backup"
    finally:
        agent2_task.cancel()
        orch_task.cancel()
        await asyncio.gather(agent2_task, orch_task, return_exceptions=True)
        await orch_ws.close()
        service.executor.shell.close()


def test_e2e_dry_run_low_risk_auto_proceed(relay_url):
    with tempfile.TemporaryDirectory() as workdir:
        asyncio.run(_flow_low_risk_auto_proceed(relay_url, workdir))


def test_e2e_dry_run_high_risk_double_approval(relay_url):
    with tempfile.TemporaryDirectory() as workdir:
        asyncio.run(_flow_high_risk_double_approval(relay_url, workdir))


def test_e2e_dry_run_disapproved_at_approval_1(relay_url):
    with tempfile.TemporaryDirectory() as workdir:
        asyncio.run(_flow_disapproved_at_approval_1(relay_url, workdir))


def test_e2e_dry_run_cancelled_at_approval_2(relay_url):
    with tempfile.TemporaryDirectory() as workdir:
        asyncio.run(_flow_cancelled_at_approval_2(relay_url, workdir))


def test_e2e_dry_run_failover(relay_url):
    with tempfile.TemporaryDirectory() as workdir:
        asyncio.run(_flow_failover(relay_url, workdir))