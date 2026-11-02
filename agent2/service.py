from __future__ import annotations

import json
import logging

from shared.messages import MessageType, envelope
from shared.net import RelayClient

from .allowlist import AllowList
from .config import Agent2Config
from .executor import Executor
from .planner import plan_for_command

logger = logging.getLogger("agent2.service")


class Agent2:
    """Laptop-side service: allow-list check → Approval #2 plan → execute.

    Connects outbound to the relay as the ``agent2`` role; no inbound ports.
    """

    def __init__(
        self,
        config: Agent2Config,
        *,
        allowlist: AllowList | None = None,
        executor: Executor | None = None,
        relay: RelayClient | None = None,
    ):
        self.config = config
        self.allowlist = allowlist or AllowList.from_file(config.allowlist_path)
        self.executor = executor or Executor()
        self.relay = relay or RelayClient(
            config.relay_url,
            config.relay_secret,
            path=config.ws_path,
            on_message=self.on_message,
        )
        self._pending: dict[str, dict] = {}

    async def on_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == MessageType.DISPATCH_COMMAND:
            await self.handle_dispatch(message)
        elif message_type == MessageType.EXECUTE_SIGNAL:
            await self.handle_execute(message)
        else:
            logger.warning("ignoring unknown message type %r", message_type)

    async def handle_dispatch(self, message: dict) -> None:
        request_id = message.get("request_id")
        user_id = message.get("user_id")
        commands = message.get("commands") or []
        if not request_id or not commands:
            await self._publish_error(request_id, "DISPATCH_COMMAND missing request_id or commands")
            return

        denied = []
        for command in commands:
            ok, reason = self.allowlist.check(command)
            if not ok:
                denied.append({"command": command, "reason": reason})
        if denied:
            details = "; ".join(f"{d['reason']}" for d in denied)
            logger.warning("request %s blocked by allow-list: %s", request_id, details)
            await self._publish_error(request_id, f"blocked by local allow-list: {details}", user_id=user_id)
            return

        plan = [plan_for_command(c) for c in commands]
        self._pending[request_id] = {"commands": commands, "plan": plan, "user_id": user_id}
        await self.relay.publish(
            envelope(MessageType.APPROVAL_2_PLAN, request_id=request_id, user_id=user_id, plan=plan)
        )

    async def handle_execute(self, message: dict) -> None:
        request_id = message.get("request_id")
        ctx = self._pending.pop(request_id, None)
        if ctx is None:
            logger.warning("execute signal for unknown/cancelled request %s", request_id)
            return
        result = self.executor.execute_all(ctx["commands"])
        payload = {
            "request_id": request_id,
            "user_id": ctx["user_id"],
            "status": result["status"],
            "cwd": result["cwd"],
            "results": result["results"],
        }
        if result.get("error"):
            payload["error"] = result["error"]
        logger.info("executed request %s: %s", request_id, result["status"])
        await self.relay.publish(envelope(MessageType.EXECUTION_RESULT, **payload))

    async def _publish_error(self, request_id: str, error: str, *, user_id=None) -> None:
        try:
            await self.relay.publish(
                envelope(MessageType.ERROR, request_id=request_id, user_id=user_id, error=error)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("failed to publish error for %s: %s", request_id, exc)

    @property
    def pending(self) -> dict[str, dict]:
        return self._pending

    @property
    def current_cwd(self) -> str:
        return self.executor.shell.cwd

    async def run(self, stop_event=None) -> None:
        """Receive loop with automatic reconnect (delegated to the relay client)."""
        await self.relay.run(stop_event)

    def __enter__(self) -> "Agent2":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.executor.shell.close()
        except Exception:
            pass


def run_service(config: Agent2Config | None = None, **kwargs) -> None:
    """Blocking entrypoint: connect to the relay and stay alive (auto-reconnects)."""
    import asyncio

    config = config or Agent2Config.from_env()
    errors = config.validate()
    if errors:
        raise RuntimeError(f"Agent 2 config missing required values: {', '.join(errors)}")
    service = Agent2(config, **kwargs)
    asyncio.run(service.run())