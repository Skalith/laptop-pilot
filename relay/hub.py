from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("relay.hub")

Peer = dict[str, Any]  # {"ws": WebSocket, "lock": asyncio.Lock}


class RelayHub:
    """Registry of relay peers + message routing.

    Roles: ``orchestrator`` and ``agent2``.
    Routing rule: a message from one role is delivered to the other role.
    Each peer's sends are serialized with its own lock to prevent interleaving.
    """

    ROLE_ORCHESTRATOR = "orchestrator"
    ROLE_AGENT2 = "agent2"
    ROLES = (ROLE_ORCHESTRATOR, ROLE_AGENT2)

    def __init__(self) -> None:
        self._peers: dict[str, Peer] = {}
        self._lock = asyncio.Lock()

    def _target_role(self, role: str) -> str:
        return self.ROLE_AGENT2 if role == self.ROLE_ORCHESTRATOR else self.ROLE_ORCHESTRATOR

    def is_online(self, role: str) -> bool:
        return role in self._peers

    async def register(self, role: str, ws: Any) -> Any:
        """Register a peer. Returns the superseded websocket, if any."""
        async with self._lock:
            previous = self._peers.pop(role, None)
            self._peers[role] = {"ws": ws, "lock": asyncio.Lock()}
        return previous["ws"] if previous else None

    async def unregister(self, role: str, ws: Any) -> None:
        async with self._lock:
            peer = self._peers.get(role)
            if peer is not None and peer["ws"] is ws:
                del self._peers[role]

    async def send_to(self, role: str, text: str) -> bool:
        """Send raw text to a peer. True if delivered."""
        async with self._lock:
            peer = self._peers.get(role)
            if peer is None:
                return False
            ws, lock = peer["ws"], peer["lock"]
        async with lock:
            await ws.send_text(text)
        return True

    async def forward(self, sender_role: str, text: str) -> bool:
        """Route a message from ``sender_role`` to the opposite role."""
        if sender_role not in self.ROLES:
            logger.warning("Unknown sender role '%s'; dropping message", sender_role)
            return True  # consumed, not an offline-target error
        return await self.send_to(self._target_role(sender_role), text)