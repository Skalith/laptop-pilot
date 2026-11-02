from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    """Per-user session state kept by the orchestrator."""

    user_id: int
    cwd: str = "~/"
    history: list[dict] = field(default_factory=list)
    last_laptop_state: dict | None = None
    auto_proceed_low_risk: bool = False

    def context(self) -> dict:
        """Session context handed to Agent 1."""
        return {
            "cwd": self.cwd,
            "conversation_history": list(self.history),
            "last_known_laptop_state": self.last_laptop_state,
            "auto_proceed_low_risk": self.auto_proceed_low_risk,
        }

    def update_cwd(self, path: str | None) -> None:
        if path:
            self.cwd = path

    def add_exchange(self, request: str, result: Any) -> None:
        self.history.append({"request": request, "result": result})
        if len(self.history) > 50:  # cap context window size
            del self.history[: len(self.history) - 50]


class SessionRegistry:
    """Registry of sessions keyed by user_id."""

    def __init__(self) -> None:
        self._sessions: dict[int, SessionState] = {}

    def get_or_create(self, user_id: int) -> SessionState:
        session = self._sessions.get(user_id)
        if session is None:
            session = SessionState(user_id=user_id)
            self._sessions[user_id] = session
        return session

    def get(self, user_id: int) -> SessionState | None:
        return self._sessions.get(user_id)

    def all(self) -> list[SessionState]:
        return list(self._sessions.values())