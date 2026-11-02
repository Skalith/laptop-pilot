from __future__ import annotations

from typing import Any


def type_text(text: str) -> dict[str, Any]:
    try:
        import pyautogui

        pyautogui.write(text)
        return {"status": "ok", "output": f"typed {len(text)} characters"}
    except Exception as exc:
        return {"status": "error", "error": f"pyautogui unavailable: {exc}"}


def press_key(key: str) -> dict[str, Any]:
    try:
        import pyautogui

        pyautogui.press(key)
        return {"status": "ok", "output": f"pressed {key}"}
    except Exception as exc:
        return {"status": "error", "error": f"pyautogui unavailable: {exc}"}


def focus_window(title_fragment: str) -> dict[str, Any]:
    try:
        import subprocess

        result = subprocess.run(
            ["wmctrl", "-a", title_fragment], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return {"status": "ok", "output": f"focused window containing '{title_fragment}'"}
        return {"status": "error", "error": f"could not focus window: {title_fragment}"}
    except (ImportError, subprocess.SubprocessError, OSError) as exc:
        return {"status": "error", "error": f"wmctrl unavailable: {exc}"}


def list_windows() -> list[str]:
    try:
        import subprocess

        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return []