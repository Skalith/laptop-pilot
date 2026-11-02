from __future__ import annotations

from .action_schema import Action

UNKNOWN_ACTION_DEFAULT_RISK = "high"

KNOWN_APPLICATIONS = {
    "vscode",
    "code",
    "code-insiders",
    "firefox",
    "chrome",
    "chromium",
    "brave",
    "terminal",
    "gnome-terminal",
    "konsole",
    "nautilus",
    "files",
    "file manager",
    "gedit",
    "text editor",
    "spotify",
    "vlc",
    "discord",
    "slack",
    "libreoffice",
}

FILE_READ_OPERATIONS = {"read", "view", "open", "cat", "ls", "list", "info", "stat"}
FILE_WRITE_OPERATIONS = {"write", "save", "append", "create", "touch"}
FILE_DELETE_OPERATIONS = {"delete", "remove", "rm", "unlink"}
SYSTEM_SETTINGS_KEYWORDS = ("credential", "password", "key", "sudo", "system", "config", "env")


def classify_risk(action: str, parameters: dict) -> str:
    """Classify a command's risk: 'low' | 'medium' | 'high'.

    Unclassified or ambiguous actions default to 'high'.
    """
    action_name = str(action).strip().upper()
    parameters = parameters or {}

    if action_name == Action.CHANGE_DIRECTORY.value:
        return "low"

    if action_name == Action.OPEN_APPLICATION.value:
        app = str(parameters.get("application", "")).strip().lower()
        return "low" if app in KNOWN_APPLICATIONS else "high"

    if action_name == Action.TAKE_SCREENSHOT.value:
        return "low"

    if action_name == Action.CLOSE_APPLICATION.value:
        return "medium"

    if action_name == Action.FILE_OPERATION.value:
        op = str(parameters.get("operation", "read")).strip().lower()
        if op in FILE_DELETE_OPERATIONS:
            return "high"
        if op in FILE_WRITE_OPERATIONS:
            return "medium"
        if op in FILE_READ_OPERATIONS:
            return "low"
        # Ambiguous file operation — default high
        return UNKNOWN_ACTION_DEFAULT_RISK

    if action_name == Action.RUN_COMMAND.value:
        command = str(parameters.get("command", ""))
        command_lower = command.lower()
        # Read-only commands are low; anything touching credentials/system is high
        if _is_read_only(command_lower):
            return "low"
        if any(keyword in command_lower for keyword in SYSTEM_SETTINGS_KEYWORDS):
            return "high"
        return "high"

    return UNKNOWN_ACTION_DEFAULT_RISK


def _is_read_only(command: str) -> bool:
    read_only_prefixes = ("ls", "pwd", "cat", "find", "grep", "echo", "df", "du", "top", "ps", "which", "whoami", "date")
    return command.startswith(read_only_prefixes)