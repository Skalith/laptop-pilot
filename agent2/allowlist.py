from __future__ import annotations

import json
import os
from typing import Any


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


class AllowList:
    """Independent local safety check ran on every command before it executes.

    A ``None`` restriction means "not restricted": e.g. ``paths=None`` allows any
    path, ``applications=None`` any application, ``commands=None`` any shell line.
    """

    def __init__(
        self,
        *,
        actions: set[str] | list[str],
        paths: set[str] | list[str] | None = None,
        applications: set[str] | list[str] | None = None,
        commands: set[str] | list[str] | None = None,
    ):
        self.actions = set(actions)
        self.paths = {_expand(p) for p in (paths or [])} if paths is not None else None
        self.applications = set(applications) if applications is not None else None
        self.commands = set(commands) if commands is not None else None

    @classmethod
    def from_config(cls, data: dict) -> "AllowList":
        return cls(
            actions=data.get("actions", []),
            paths=data.get("paths"),
            applications=data.get("applications"),
            commands=data.get("commands"),
        )

    @classmethod
    def from_file(cls, path: str) -> "AllowList":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_config(json.load(handle))

    def _path_allowed(self, path: str) -> bool:
        expanded = _expand(path)
        for root in self.paths or ():
            root = _expand(root)
            if expanded == root:
                return True
            prefix = os.sep if root == os.sep else f"{root.rstrip(os.sep)}{os.sep}"
            if expanded.startswith(prefix):
                return True
        return False

    def check(self, command: dict) -> tuple[bool, str]:
        action = command.get("action")
        if action not in self.actions:
            return False, f"action not allowed: {action}"
        params: dict[str, Any] = command.get("parameters") or {}

        if action in ("CHANGE_DIRECTORY", "FILE_OPERATION"):
            target = params.get("path")
            if self.paths is not None:
                if not target:
                    return False, f"{action} requires a path"
                if not self._path_allowed(target):
                    return False, f"path not allowed: {target}"

        if action in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
            app = (params.get("application") or params.get("name") or "").lower()
            if self.applications is not None:
                allowed = {a.lower() for a in self.applications}
                if app not in allowed:
                    return False, f"application not allowed: {app or '<none>'}"

        if action == "RUN_COMMAND":
            cmd = (params.get("command") or "").strip()
            if self.commands is not None and cmd:
                name = cmd.split(" ", 1)[0]
                if name not in self.commands:
                    return False, f"command not allowed: {name}"

        return True, ""