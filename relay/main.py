from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .auth import authenticate
from .hub import RelayHub

logger = logging.getLogger("relay")

load_dotenv()
RELAY_SECRET = os.environ.get("RELAY_SECRET", "")
RELAY_TOKEN_PARAM = "token"


@asynccontextmanager
async def lifespan(_app):
    if not RELAY_SECRET:
        raise RuntimeError("RELAY_SECRET is not set — refusing to start the relay")
    yield


app = FastAPI(title="LaptopPilot Relay", lifespan=lifespan)

hub = RelayHub()


@app.get("/health")
async def health() -> dict:
    online = {role: hub.is_online(role) for role in hub.ROLES}
    return {"status": "ok", "peers": online}


@app.websocket("/ws/orchestrator")
async def ws_orchestrator(ws: WebSocket) -> None:
    await _handle_peer(ws, RelayHub.ROLE_ORCHESTRATOR)


@app.websocket("/ws/agent2")
async def ws_agent2(ws: WebSocket) -> None:
    await _handle_peer(ws, RelayHub.ROLE_AGENT2)


async def _handle_peer(ws: WebSocket, role: str) -> None:
    if not await authenticate(ws, RELAY_SECRET):
        logger.warning("Rejected unauthenticated %s connection", role)
        # Close before accept to reject the handshake
        try:
            await ws.close(code=4401, reason="unauthorized")
        except Exception:  # pragma: no cover - starlette close edge cases
            logger.exception("Failed to close unauthorized socket")
        return

    await ws.accept()
    logger.info("%s connected", role)
    superseded = await hub.register(role, ws)
    if superseded is not None:
        logger.info("%s superseded by a new connection", role)
        try:
            await superseded.close(code=4001, reason="superseded")
        except Exception:
            pass

    try:
        while True:
            text = await ws.receive_text()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from %s", role)
                await hub.send_to(role, json.dumps({"type": "ERROR", "error": "invalid_json"}))
                continue

            delivered = await hub.forward(role, text)
            if not delivered:
                logger.info("message from %s dropped: target offline", role)
                response = {"type": "ERROR", "error": "target_not_online", "original": payload}
                await hub.send_to(role, json.dumps(response))
    except WebSocketDisconnect:
        pass  # client left — cleanup in finally
    finally:
        await hub.unregister(role, ws)
        logger.info("%s disconnected", role)


__all__ = ["app", "hub", "RELAY_SECRET"]