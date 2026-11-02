from __future__ import annotations

import subprocess

PERMISSION_PATTERNS = (
    "sudo",
    "password",
    "authenticate",
    "permission",
    "allow access",
    "allow the app",
    "permission required",
)


def _window_titles() -> list[str]:
    try:
        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return []


def scan_titles(titles: list[str]) -> list[str]:
    """Return the dialog titles that look like a permission/credential prompt."""
    lowered = " ".join(titles).lower()
    return [pattern for pattern in PERMISSION_PATTERNS if pattern in lowered]


def detect_permission_dialogs() -> list[str]:
    """Detect permission/credential dialogs currently on screen. Never auto-acts."""
    return scan_titles(_window_titles())