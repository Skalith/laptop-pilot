from __future__ import annotations

import os
from typing import Any


def perform(parameters: dict) -> dict:
    """Execute a FILE_OPERATION using plain filesystem calls."""
    op = parameters.get("operation") or "read"
    path = os.path.expanduser(parameters.get("path") or "")

    if op == "read":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            return {"status": "ok", "operation": op, "path": path, "output": content[:4000]}
        except FileNotFoundError:
            return {"status": "error", "operation": op, "path": path, "error": f"file not found: {path}"}
        except OSError as exc:
            return {"status": "error", "operation": op, "path": path, "error": str(exc)}

    if op in ("write", "save"):
        content = parameters.get("content") or ""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            return {"status": "ok", "operation": "write", "path": path, "output": f"wrote {len(content)} bytes to {path}"}
        except OSError as exc:
            return {"status": "error", "operation": "write", "path": path, "error": str(exc)}

    if op in ("delete", "remove"):
        try:
            os.remove(path)
            return {"status": "ok", "operation": "delete", "path": path, "output": f"deleted {path}"}
        except FileNotFoundError:
            return {"status": "error", "operation": "delete", "path": path, "error": f"file not found: {path}"}
        except OSError as exc:
            return {"status": "error", "operation": "delete", "path": path, "error": str(exc)}

    return {"status": "error", "operation": op, "error": f"unsupported file operation: {op}"}