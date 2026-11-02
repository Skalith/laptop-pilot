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
from shared.messages import MessageType
from shared.net import RelayClient

from ..allowlist import AllowList
from ..config import Agent2Config
from ..executor import Executor
from ..service import Agent2


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


async def _collect(queue, message_type, timeout=10.0):
    async def waiter():
        while True:
            item = await queue.get()
            if item.get("type") == message_type:
                return item

    return await asyncio.wait_for(waiter(), timeout=timeout)


def test_end_to_end_dispatch_plan_execute(relay_url):
    asyncio.run(_scenario(relay_url))


async def _scenario(relay_url: str) -> None:
    with tempfile.TemporaryDirectory() as workdir:
        inbox: asyncio.Queue = asyncio.Queue()

        async def on_message(message: dict) -> None:
            await inbox.put(message)

        allow = AllowList(
            actions=["CHANGE_DIRECTORY", "TAKE_SCREENSHOT"],
            paths=None,
            commands=None,
            applications=None,
        )
        config = Agent2Config(relay_url=relay_url, relay_secret="test-secret")
        service = Agent2(config, allowlist=allow, executor=Executor())
        orchestrator = RelayClient(relay_url, "test-secret", path="/ws/orchestrator", on_message=on_message)

        agent2_task = asyncio.create_task(service.run())
        orch_task = asyncio.create_task(orchestrator.run())
        try:
            await asyncio.sleep(0.4)  # both clients connect to the relay

            await orchestrator.publish(
                {
                    "type": MessageType.DISPATCH_COMMAND,
                    "request_id": "e2e-1",
                    "user_id": 111,
                    "commands": [
                        {"action": "CHANGE_DIRECTORY", "parameters": {"path": workdir}, "risk": "low"},
                        {"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"},
                    ],
                }
            )

            plan_msg = await _collect(inbox, MessageType.APPROVAL_2_PLAN)
            assert plan_msg["request_id"] == "e2e-1"
            assert plan_msg["plan"]

            await orchestrator.publish({"type": MessageType.EXECUTE_SIGNAL, "request_id": "e2e-1"})

            result = await _collect(inbox, MessageType.EXECUTION_RESULT)
            assert result["status"] == "ok"
            assert os.path.realpath(result["cwd"]) == os.path.realpath(workdir)
            assert result["results"][1]["mime"] == "image/png"
        finally:
            agent2_task.cancel()
            orch_task.cancel()
            await asyncio.gather(agent2_task, orch_task, return_exceptions=True)
            await orchestrator.close()
        service.executor.shell.close()