from __future__ import annotations

from typing import Any

from .executor import processes, screen


def snapshot_state() -> dict[str, Any]:
    """Collect a best-effort snapshot of the laptop state for session context."""
    screenshot = screen.take_screenshot()
    return {
        "windows": _window_titles(),
        "processes": processes.list_processes(),
        "screen": screenshot,
    }


def _window_titles() -> list[str]:
    try:
        from .executor import gui

        return gui.list_windows()
    except Exception:
        return []