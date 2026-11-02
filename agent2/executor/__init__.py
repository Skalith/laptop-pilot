from __future__ import annotations

from typing import Any

from . import files, gui, processes, screen
from .terminal import PersistentShell, ShellResult

__all__ = ["Executor", "PersistentShell", "ShellResult", "files", "gui", "processes", "screen"]


def _command_name(command: dict) -> str:
    params = command.get("parameters") or {}
    return (
        params.get("application")
        or params.get("path")
        or params.get("command")
        or command.get("action")
    )


class Executor:
    """Runs already-approved commands against the real laptop.

    ``shell`` is a ``PersistentShell`` (kept across commands). ``commands`` have
    already passed the allow-list (checked by the service) and both approvals.
    """

    def __init__(self, shell: PersistentShell | None = None, *, screenshot_timeout: float = 5.0):
        self.shell = shell or PersistentShell()
        self.screenshot_timeout = screenshot_timeout

    def run(self, command: dict) -> dict[str, Any]:
        action = command.get("action")
        params = command.get("parameters") or {}
        name = _command_name(command)
        base = {"command": command, "name": name}

        if action == "CHANGE_DIRECTORY":
            result: ShellResult = self.shell.change_directory(params.get("path") or ".")
            return {**base, "status": "ok" if result.exit_code == 0 else "error", "exit_code": result.exit_code, "output": result.output}
        if action == "RUN_COMMAND":
            result = self.shell.run(params.get("command") or "")
            return {**base, "status": "ok" if result.exit_code == 0 else "error", "exit_code": result.exit_code, "output": result.output}
        if action == "OPEN_APPLICATION":
            return {**base, **processes.open_application(params)}
        if action == "CLOSE_APPLICATION":
            return {**base, **processes.close_application(params)}
        if action == "FILE_OPERATION":
            return {**base, **files.perform(params)}
        if action == "TAKE_SCREENSHOT":
            shot = screen.take_screenshot(self.screenshot_timeout)
            return {**base, "status": "ok", **shot}
        return {**base, "status": "error", "error": f"unknown action: {action}"}

    def execute_all(self, commands: list[dict]) -> dict[str, Any]:
        results = [self.run(c) for c in commands]
        failures = [r for r in results if r.get("status") == "error"]
        return {
            "status": "ok" if not failures else "error",
            "results": results,
            "cwd": self.shell.cwd,
            "error": "; ".join(f"{r['name']}: {r.get('error')}" for r in failures) if failures else None,
        }

    def __enter__(self) -> "Executor":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.shell.close()
        except Exception:
            pass