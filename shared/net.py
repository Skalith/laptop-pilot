from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

logger = logging.getLogger("shared.net")

MessageCallback = Callable[[dict], Awaitable[None]]


class RelayClient:
    """Outbound WebSocket client used to talk to the relay.

    Connects as a given role (``/ws/orchestrator`` or ``/ws/agent2``) and
    auto-reconnects. Shared by the orchestrator and Agent 2.
    """

    def __init__(
        self,
        relay_url: str,
        relay_secret: str,
        *,
        path: str = "/ws/orchestrator",
        on_message: MessageCallback | None = None,
        reconnect_delay: float = 2.0,
    ):
        self.relay_url = relay_url
        self.relay_secret = relay_secret
        self.path = path
        self.on_message = on_message
        self.reconnect_delay = reconnect_delay
        self._ws = None

    @property
    def connection_url(self) -> str:
        base = self.relay_url.rstrip("/")
        return f"{base}{self.path}?token={self.relay_secret}"

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.connection_url)
        logger.info("connected to relay at %s", self.relay_url)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def publish(self, message: dict) -> None:
        if self._ws is None:
            await self.connect()
        await self._ws.send(json.dumps(message))

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Receive loop with automatic reconnect. Blocks until stopped."""
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            try:
                if self._ws is None:
                    await self.connect()
                async for raw in self._ws:
                    payload = json.loads(raw)
                    if self.on_message:
                        await self.on_message(payload)
            except Exception as exc:  # network error or disconnect
                logger.warning("relay connection lost: %s", exc)
                self._ws = None
                try:
                    await asyncio.sleep(self.reconnect_delay)
                except asyncio.CancelledError:
                    break