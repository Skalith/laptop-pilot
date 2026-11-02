from __future__ import annotations

import asyncio

import pytest

from agent2.allowlist import AllowList
from agent2.config import Agent2Config
from agent2.executor import Executor
from agent2.service import Agent2


class FakeRelay:
    def __init__(self, publish_error=None):
        self.published: list[dict] = []
        self.publish_error = publish_error
        self.run_calls = 0

    async def publish(self, message: dict) -> None:
        if self.publish_error:
            raise self.publish_error
        self.published.append(message)

    async def run(self, stop_event=None) -> None:
        self.run_calls += 1


ALLOW_ALL = AllowList(
    actions=["CHANGE_DIRECTORY", "OPEN_APPLICATION", "RUN_COMMAND", "FILE_OPERATION", "CLOSE_APPLICATION", "TAKE_SCREENSHOT"],
    paths=None,
    applications=None,
    commands=None,
)


def build_service(relay: FakeRelay, *, executor: Executor | None = None, allowlist: AllowList | None = None) -> Agent2:
    config = Agent2Config(relay_url="ws://x", relay_secret="s")
    return Agent2(
        config,
        allowlist=allowlist or ALLOW_ALL,
        executor=executor or Executor(),
        relay=relay,
    )


def dispatch_msg(commands, request_id="r1", user_id=111) -> dict:
    return {"type": "DISPATCH_COMMAND", "request_id": request_id, "user_id": user_id, "commands": commands}


class TestDispatch:
    def test_allowed_plan_is_published(self):
        relay = FakeRelay()
        with build_service(relay) as service:
            asyncio.run(
                service.handle_dispatch(dispatch_msg([{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}]))
            )
        assert relay.published[0]["type"] == "APPROVAL_2_PLAN"
        assert relay.published[0]["user_id"] == 111
        assert relay.published[0]["plan"]

    def test_request_is_kept_pending_for_execute(self):
        relay = FakeRelay()
        service = build_service(relay)
        asyncio.run(service.handle_dispatch(dispatch_msg([{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}])))
        assert "r1" in service.pending
        assert service.pending["r1"]["plan"]
        service.executor.shell.close()

    def test_blocked_command_publishes_error_and_is_not_pending(self):
        relay = FakeRelay()
        allow = AllowList(actions=["TAKE_SCREENSHOT"])
        service = build_service(relay, allowlist=allow)
        asyncio.run(service.handle_dispatch(dispatch_msg([{"action": "RUN_COMMAND", "parameters": {"command": "rm -rf /"}, "risk": "high"}])))
        assert relay.published[0]["type"] == "ERROR"
        assert "allow-list" in relay.published[0]["error"]
        assert not service.pending
        service.executor.shell.close()

    def test_partial_denial_blocks_whole_request(self):
        relay = FakeRelay()
        allow = AllowList(actions=["TAKE_SCREENSHOT", "CHANGE_DIRECTORY"])
        service = build_service(relay, allowlist=allow)
        asyncio.run(
            service.handle_dispatch(
                dispatch_msg([
                    {"action": "CHANGE_DIRECTORY", "parameters": {"path": "/tmp"}, "risk": "low"},
                    {"action": "RUN_COMMAND", "parameters": {"command": "id"}, "risk": "high"},
                ])
            )
        )
        assert relay.published[0]["type"] == "ERROR"
        assert not service.pending
        service.executor.shell.close()


class TestExecute:
    def test_execute_publishes_result_and_drains_pending(self):
        relay = FakeRelay()
        service = build_service(relay)
        asyncio.run(service.handle_dispatch(dispatch_msg([{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}])))
        asyncio.run(service.handle_execute({"type": "EXECUTE_SIGNAL", "request_id": "r1"}))
        msg = relay.published[-1]
        assert msg["type"] == "EXECUTION_RESULT"
        assert msg["request_id"] == "r1"
        assert msg["user_id"] == 111
        assert msg["results"][0]["mime"] == "image/png"
        assert service.pending == {}
        service.executor.shell.close()

    def test_execute_without_plan_is_ignored(self):
        relay = FakeRelay()
        service = build_service(relay)
        asyncio.run(service.handle_execute({"type": "EXECUTE_SIGNAL", "request_id": "never-sent"}))
        assert relay.published == []
        service.executor.shell.close()

    def test_execute_reports_failed_command_in_result(self):
        relay = FakeRelay()
        service = build_service(relay)
        asyncio.run(
            service.handle_dispatch(dispatch_msg([{"action": "RUN_COMMAND", "parameters": {"command": "bash -c 'exit 3'"}, "risk": "high"}]))
        )
        asyncio.run(service.handle_execute({"type": "EXECUTE_SIGNAL", "request_id": "r1"}))
        msg = relay.published[-1]
        assert msg["status"] == "error"
        assert msg["results"][0]["exit_code"] == 3
        service.executor.shell.close()


class TestMessageLoop:
    def test_unknown_message_type_ignored(self):
        relay = FakeRelay()
        service = build_service(relay)
        asyncio.run(service.on_message({"type": "BOGUS"}))
        assert relay.published == []
        service.executor.shell.close()

    def test_publish_failure_does_not_crash_for_denied(self):
        relay = FakeRelay(publish_error=ConnectionError("relay down"))
        allow = AllowList(actions=["TAKE_SCREENSHOT"])
        service = build_service(relay, allowlist=allow)
        asyncio.run(
            service.handle_dispatch(dispatch_msg([{"action": "RUN_COMMAND", "parameters": {"command": "rm"}, "risk": "high"}]))
        )
        assert relay.published == []
        service.executor.shell.close()


class TestReconnect:
    def test_run_survives_disconnect(self):
        class FlakyRelay(FakeRelay):
            async def run(self, stop_event=None):
                self.run_calls += 1
                raise ConnectionError("simulated disconnect")

        relay = FlakyRelay()
        service = build_service(relay)
        with pytest.raises(ConnectionError):
            asyncio.run(service.run())
        assert relay.run_calls == 1
        service.executor.shell.close()