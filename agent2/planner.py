from __future__ import annotations

from typing import Any


def plan_for_command(command: dict) -> list[str]:
    """Translate one abstract command into concrete, step-by-step human-readable steps."""
    action = command.get("action")
    params: dict[str, Any] = command.get("parameters") or {}
    path = params.get("path") or ""
    app = params.get("application") or params.get("name") or ""
    target = params.get("target") or ""
    cmd = params.get("command") or ""

    if action == "CHANGE_DIRECTORY":
        return [
            f"Run 'cd {path}' in the persistent shell session",
            f"Verify the current working directory is now '{path}'",
        ]
    if action == "OPEN_APPLICATION":
        steps = [f"Check whether '{app}' is already running"]
        steps.append(f"Launch '{app}'" + (f" with target '{target}'" if target else ""))
        steps.append("Wait for the application window to appear")
        steps.append("Confirm the window is active and focused")
        return steps
    if action == "CLOSE_APPLICATION":
        return [f"Check whether '{app}' is running", f"Close '{app}' gracefully"]
    if action == "RUN_COMMAND":
        return [f"Run '{cmd}' in the persistent shell session", "Capture stdout, stderr, and exit code"]
    if action == "FILE_OPERATION":
        op = params.get("operation") or "read"
        if op == "delete":
            return [f"Delete '{path}'", "Verify the file no longer exists"]
        if op == "write":
            return [f"Write provided content to '{path}'", "Verify the file was saved"]
        return [f"Read the contents of '{path}'"]
    if action == "TAKE_SCREENSHOT":
        return ["Capture the current screen", "Attach the screenshot to the result"]
    return [f"Execute action '{action}' with parameters {params}"]


def plan_commands(commands: list[dict]) -> list[dict]:
    """Build the full Approval #2 plan: per-command action + its steps."""
    return [
        {"command": {"action": c.get("action"), "parameters": c.get("parameters", {})}, "steps": plan_for_command(c)}
        for c in commands
    ]