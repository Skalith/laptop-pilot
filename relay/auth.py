from __future__ import annotations

from fastapi import WebSocket


async def authenticate(ws: WebSocket, expected_secret: str) -> bool:
    """Verify a peer's shared secret (query token or Bearer header).

    Fails secure: missing/empty expected_secret rejects everyone.
    """
    if not expected_secret:
        return False
    token = ws.query_params.get("token", "")
    if token:
        return token == expected_secret
    header = ws.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() == expected_secret
    return False