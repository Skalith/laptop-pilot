from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import nullcontext
from typing import Callable

from shared.messages import EventType
from shared.tracing.langfuse import start_trace

from .approvals import APPROVAL_KIND_1, APPROVAL_KIND_2, ApprovalStore
from .audit import AuditLogger
from .auth import SenderAuth
from .config import Settings
from .session import SessionRegistry

from agent1.agent import Agent1

logger = logging.getLogger("orchestrator.pipeline")

Agent1Callable = Callable[[str, dict], list[dict]]  # (request, session_context) -> commands
Dispatcher = Callable[[list[dict], str], None]       # (commands, request_id) -> dispatch to Agent 2
ExecuteSignal = Callable[[str], None]                # (request_id) -> signal Agent 2 to execute

RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _span(trace, name: str, **metadata):
    """Open a tracing span, or a no-op when there is no active trace."""
    if trace is None:
        return nullcontext()
    return trace.span(name, **metadata)


class StubAgent1:
    """Development stand-in for Agent 1 (dry-run pipeline)."""

    def __call__(self, request: str, session_context: dict) -> list[dict]:
        return [
            {
                "action": "TAKE_SCREENSHOT",
                "parameters": {},
                "risk": "low",
            }
        ]


class Orchestrator:
    """Core control flow: auth → request → Agent 1 → Approval #1 → dispatch.

    Agent 1 and dispatch are injected so this is fully testable with mocks.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        auth: SenderAuth | None = None,
        sessions: SessionRegistry | None = None,
        approvals: ApprovalStore | None = None,
        audit: AuditLogger | None = None,
        agent1: Agent1Callable | None = None,
        dispatcher: Dispatcher | None = None,
        execute_signal: ExecuteSignal | None = None,
        time_func: Callable[[], float] | None = None,
    ):
        self.settings = settings
        self.auth = auth or SenderAuth(settings.authorized_user_ids)
        self.sessions = sessions or SessionRegistry()
        self.approvals = approvals or ApprovalStore(settings.approval_ttl_seconds)
        self.audit = audit or AuditLogger(settings.log_path)
        self.agent1 = agent1 or StubAgent1()
        self.dispatcher = dispatcher
        self.execute_signal = execute_signal
        self.time_func = time_func or time.time
        self._request_users: dict[str, int] = {}
        self._request_risk: dict[str, str] = {}
        self._traces: dict[str, object] = {}
        self._inflight: dict[str, float] = {}

    def handle_request(self, user_id: int, text: str) -> dict:
        """Full pipeline for an inbound natural-language request."""
        if not self.auth.is_authorized(user_id):
            self.audit.log(EventType.ERROR, str(user_id), f"REJECTED unauthorized sender: {text[:100]}")
            return {"status": "rejected", "reason": "unauthorized"}

        session = self.sessions.get_or_create(user_id)
        if self.settings.auto_proceed_low_risk and not session.auto_proceed_low_risk:
            session.auto_proceed_low_risk = True
        request_id = str(uuid.uuid4())
        self._request_users[request_id] = user_id
        self.audit.log(EventType.REQUEST_RECEIVED, str(user_id), text[:500])
        trace = start_trace(request_id, str(user_id))
        self._traces[request_id] = trace

        try:
            if isinstance(self.agent1, Agent1):
                commands = self.agent1.generate_commands(text, session.context(), trace=trace)
            else:
                commands = self.agent1(text, session.context())
        except Exception as exc:
            logger.exception("Agent 1 failed")
            self.audit.log(EventType.ERROR, str(user_id), f"agent1: {exc}")
            return {"status": "error", "request_id": request_id, "error": f"agent1: {exc}"}

        if not commands:
            self.audit.log(EventType.ERROR, str(user_id), "agent1 returned empty command list")
            return {"status": "error", "request_id": request_id, "error": "agent1 returned no commands"}

        self.audit.log(EventType.COMMAND_GENERATED, str(user_id), json.dumps(commands))
        max_risk = max(RISK_RANK.get(c.get("risk", "high"), 2) for c in commands)
        max_risk_name = next(name for name, rank in RISK_RANK.items() if rank == max_risk)
        self._request_risk[request_id] = max_risk_name

        with _span(trace, "COMMAND_GENERATED", risk=max_risk_name, count=len(commands)):
            pass

        if max_risk_name == "low" and session.auto_proceed_low_risk:
            self._dispatch(user_id, commands, request_id, trace=trace)
            return {
                "status": "dispatched",
                "request_id": request_id,
                "commands": commands,
                "auto_proceeded": True,
            }

        self.approvals.add(
            request_id,
            APPROVAL_KIND_1,
            {"commands": commands, "risk": max_risk_name, "user_id": user_id, "text": text},
        )
        self.audit.log(EventType.APPROVAL_1_SENT, str(user_id), request_id)
        return {
            "status": "awaiting_approval_1",
            "request_id": request_id,
            "commands": commands,
            "risk": max_risk_name,
        }

    def handle_approval_1(self, request_id: str, decision: str, user_id: int) -> dict:
        """Decision from Approval #1: 'approve' or 'disapprove'."""
        approval = self.approvals.resolve(request_id)
        if approval is None:
            return {"status": "not_found", "request_id": request_id, "reason": "no pending approval (expired or already handled)"}

        trace = self._traces.get(request_id)
        details = f"request={request_id} decision={decision}"
        if decision == "approve":
            self.audit.log(EventType.APPROVAL_1_RESULT, str(user_id), f"approved {details}")
            commands = approval.payload["commands"]
            self._dispatch(user_id, commands, request_id, trace=trace)
            with _span(trace, "APPROVAL_1_RESULT", decision="approve"):
                pass
            return {"status": "dispatched", "request_id": request_id, "commands": commands}
        self.audit.log(EventType.APPROVAL_1_RESULT, str(user_id), f"disapproved {details}")
        with _span(trace, "APPROVAL_1_RESULT", decision="disapprove"):
            pass
        return {"status": "stopped", "request_id": request_id}

    def handle_approval_2(self, request_id: str, decision: str, user_id: int) -> dict:
        """Decision from Approval #2: 'execute' or 'cancel'."""
        approval = self.approvals.resolve(request_id)
        if approval is None:
            return {"status": "not_found", "request_id": request_id, "reason": "no pending approval (expired or already handled)"}

        if decision == "execute":
            self.audit.log(EventType.APPROVAL_2_RESULT, str(user_id), f"execute request={request_id}")
            self._send_execute(user_id, request_id)
            trace = self._traces.get(request_id)
            with _span(trace, "APPROVAL_2_RESULT", decision="execute"):
                pass
            return {"status": "executing", "request_id": request_id}
        self.audit.log(EventType.APPROVAL_2_RESULT, str(user_id), f"cancel request={request_id}")
        trace = self._traces.get(request_id)
        with _span(trace, "APPROVAL_2_RESULT", decision="cancel"):
            pass
        return {"status": "stopped", "request_id": request_id}

    def handle_agent2_plan(self, request_id: str, plan: list | dict, user_id: int) -> dict:
        """Agent 2 sent its execution plan — hold it for Approval #2."""
        session = self.sessions.get_or_create(user_id)
        self._request_users[request_id] = user_id
        self._inflight.pop(request_id, None)
        self.approvals.add(
            request_id,
            APPROVAL_KIND_2,
            {"plan": plan, "user_id": user_id},
        )
        self.audit.log(EventType.APPROVAL_2_SENT, str(user_id), request_id)
        return {"status": "awaiting_approval_2", "request_id": request_id, "plan": plan}

    def handle_agent2_result(self, request_id: str, result: dict) -> dict:
        """Agent 2 executed — record result, audit it, update session state."""
        self._inflight.pop(request_id, None)
        user_id = result.get("user_id") or self._request_users.get(request_id) or ""
        self.audit.log(EventType.EXECUTION_RESULT, str(user_id), json.dumps(result)[:2000])

        session = self.sessions.get(user_id)
        if session is not None:
            session.update_cwd(result.get("cwd"))
            if result.get("state") is not None:
                session.last_laptop_state = result["state"]
            session.add_exchange(request_id, result)
        trace = self._traces.pop(request_id, None)
        if trace is not None:
            with _span(trace, "EXECUTION_RESULT", status=result.get("status"), request_id=request_id):
                pass
            trace.end()
        self._request_risk.pop(request_id, None)
        self._request_users.pop(request_id, None)
        return {"status": "recorded", "request_id": request_id}

    def risk_for(self, request_id: str) -> str | None:
        """Risk level recorded when the request's commands were generated."""
        return self._request_risk.get(request_id)

    def request_user(self, request_id: str) -> int | None:
        """Telegram user that originated a request, while it is in flight."""
        return self._request_users.get(request_id)

    def sweep_expired_approvals(self) -> list[str]:
        """Auto-cancel expired approvals, logging APPROVAL_EXPIRED for each."""
        expired = self.approvals.expire_due()
        for approval in expired:
            self.audit.log(
                EventType.APPROVAL_EXPIRED,
                str(approval.payload.get("user_id", "")),
                f"request={approval.request_id} kind={approval.kind} ttl={self.settings.approval_ttl_seconds}s",
            )
        return [a.request_id for a in expired]

    def sweep_stale_dispatches(self) -> list[str]:
        """Detect dispatches Agent 2 never answered (relay down / laptop offline) and log ERROR.

        Returns the stale request ids so callers can notify the user via the bot.
        """
        now = self.time_func()
        stale = [
            request_id
            for request_id, deadline in self._inflight.items()
            if deadline <= now
        ]
        for request_id in stale:
            user_id = self._request_users.get(request_id, "")
            self._inflight.pop(request_id, None)
            self.audit.log(
                EventType.ERROR,
                str(user_id),
                f"Agent 2 did not respond within {self.settings.dispatch_timeout_seconds}s for request {request_id}",
            )
        return stale

    def _dispatch(self, user_id: int, commands: list[dict], request_id: str, *, trace=None) -> None:
        if self.dispatcher is None:
            self.audit.log(EventType.COMMAND_DISPATCHED, str(user_id), f"{request_id} DRY_RUN no dispatcher")
            return
        try:
            self.dispatcher(commands, request_id)
            self.audit.log(EventType.COMMAND_DISPATCHED, str(user_id), request_id)
            self._inflight[request_id] = self.time_func() + self.settings.dispatch_timeout_seconds
            with _span(trace, "COMMAND_DISPATCHED", request_id=request_id):
                pass
        except Exception as exc:
            logger.exception("dispatch failed")
            self.audit.log(EventType.ERROR, str(user_id), f"dispatch failed: {exc}")

    def _send_execute(self, user_id: int, request_id: str) -> None:
        if self.execute_signal is None:
            self.audit.log(EventType.ERROR, str(user_id), f"execute request={request_id} DRY_RUN no execute_signal")
            return
        try:
            self.execute_signal(request_id)
        except Exception as exc:
            logger.exception("execute signal failed")
            self.audit.log(EventType.ERROR, str(user_id), f"execute signal failed: {exc}")