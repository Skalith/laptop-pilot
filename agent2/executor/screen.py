from __future__ import annotations

import base64
import io
import struct
import subprocess
import zlib
from typing import Any


def _synthetic_png(width: int = 320, height: int = 180) -> bytes:
    """Build a valid small PNG with stdlib only (headless fallback)."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        for x in range(width):
            raw.extend(bytes(((x * 3 + y * 5) % 256, (x * 5 + y * 7) % 256, (x * 2 + y * 11) % 256)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    return png


def _capture_scrot(timeout: float) -> bytes | None:
    try:
        result = subprocess.run(["scrot", "-o", "-"], capture_output=True, timeout=timeout)
        if result.returncode == 0 and result.stdout.startswith(b"\x89PNG"):
            return result.stdout
    except (subprocess.SubprocessError, OSError):
        return None
    return None


def _capture_pillow() -> bytes | None:
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def take_screenshot(timeout: float = 5.0) -> dict[str, Any]:
    """Capture the screen. Uses scrot, then Pillow, then a synthetic PNG fallback."""
    raw = _capture_scrot(timeout) or _capture_pillow()
    source = "scrot" if raw is not None else "pillow"
    if raw is None:
        raw = _synthetic_png()
        source = "synthetic"
    return {
        "status": "ok",
        "mime": "image/png",
        "source": source,
        "screenshot_b64": base64.b64encode(raw).decode(),
    }


def is_valid_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")