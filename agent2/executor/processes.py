from __future__ import annotations

import subprocess
from typing import Any


def open_application(parameters: dict) -> dict:
    """Launch an application, optionally on a target path. Error-tolerant in headless/dev envs."""
    app = parameters.get("application") or parameters.get("name") or ""
    target = parameters.get("target") or parameters.get("path") or ""
    if not app:
        return {"status": "error", "error": "no application specified"}

    command = [app] + ([target] if target else [])
    try:
        subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "ok", "output": f"launched {app}", "pid": None}
    except FileNotFoundError:
        try:
            subprocess.Popen(["xdg-open", target or app], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"status": "ok", "output": f"launched via xdg-open {target or app}"}
        except (FileNotFoundError, OSError) as exc:
            return {"status": "error", "error": f"could not launch {app}: {exc}"}
    except OSError as exc:
        return {"status": "error", "error": f"could not launch {app}: {exc}"}


def close_application(parameters: dict) -> dict:
    """Close an application by name (graceful pkill)."""
    app = parameters.get("application") or parameters.get("name") or ""
    if not app:
        return {"status": "error", "error": "no application specified"}
    try:
        subprocess.run(["pkill", "-f", app], capture_output=True, timeout=10)
        return {"status": "ok", "output": f"requested close of {app}"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"status": "error", "error": f"could not close {app}: {exc}"}


def list_processes() -> list[str]:
    """Return the names of running processes (best effort)."""
    try:
        result = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True, timeout=10)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return []