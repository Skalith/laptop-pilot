from __future__ import annotations

import json

import pytest

from agent2.allowlist import AllowList


def default_actions() -> list[str]:
    return ["CHANGE_DIRECTORY", "OPEN_APPLICATION", "RUN_COMMAND", "FILE_OPERATION", "CLOSE_APPLICATION", "TAKE_SCREENSHOT"]


def make_allowlist(**kwargs) -> AllowList:
    return AllowList(actions=kwargs.pop("actions", default_actions()), **kwargs)


class TestPermitted:
    def test_allowed_action_passes(self):
        allow = make_allowlist()
        ok, reason = allow.check({"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"})
        assert ok and reason == ""

    def test_change_directory_within_allowed_root(self):
        allow = make_allowlist(paths=["/"])
        ok, _ = allow.check({"action": "CHANGE_DIRECTORY", "parameters": {"path": "/tmp"}, "risk": "low"})
        assert ok

    def test_run_command_matching_allowed_prefix(self):
        allow = make_allowlist(commands=["ls", "cat"])
        ok, _ = allow.check({"action": "RUN_COMMAND", "parameters": {"command": "ls -la"}, "risk": "high"})
        assert ok

    def test_open_application_on_allowlist(self):
        allow = make_allowlist(applications=["vscode", "code"])
        ok, _ = allow.check({"action": "OPEN_APPLICATION", "parameters": {"application": "code", "target": "~/x"}, "risk": "low"})
        assert ok


class TestDenied:
    def test_unknown_action_rejected(self):
        allow = make_allowlist()
        ok, reason = allow.check({"action": "FORMAT_DISK", "parameters": {}, "risk": "high"})
        assert not ok and "action not allowed" in reason

    def test_path_outside_allowed_root_rejected(self):
        allow = make_allowlist(paths=["/home/me/projects"])
        ok, reason = allow.check({"action": "FILE_OPERATION", "parameters": {"operation": "delete", "path": "/etc/passwd"}, "risk": "high"})
        assert not ok and "path not allowed" in reason

    def test_disallowed_shell_command_rejected(self):
        allow = make_allowlist(commands=["ls"])
        ok, reason = allow.check({"action": "RUN_COMMAND", "parameters": {"command": "rm -rf /"}, "risk": "high"})
        assert not ok and "command not allowed" in reason

    def test_app_not_on_allowlist_rejected(self):
        allow = make_allowlist(applications=["vscode"])
        ok, reason = allow.check({"action": "OPEN_APPLICATION", "parameters": {"application": "firefox"}, "risk": "low"})
        assert not ok and "application not allowed" in reason

    def test_file_operation_requires_path(self):
        allow = make_allowlist(paths=["/"])
        ok, reason = allow.check({"action": "FILE_OPERATION", "parameters": {"operation": "delete"}, "risk": "high"})
        assert not ok and "requires a path" in reason


class TestConfigLoading:
    def test_from_config_dict(self):
        data = {"actions": ["TAKE_SCREENSHOT"], "paths": ["~"]}
        allow = AllowList.from_config(data)
        ok, _ = allow.check({"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"})
        assert ok
        ok2, _ = allow.check({"action": "RUN_COMMAND", "parameters": {"command": "ls"}, "risk": "high"})
        assert not ok2

    def test_from_file(self, tmp_path):
        path = tmp_path / "allowlist.json"
        path.write_text(json.dumps({"actions": ["CHANGE_DIRECTORY"], "paths": [str(tmp_path)]}))
        allow = AllowList.from_file(str(path))
        newdir = tmp_path / "sub"
        ok, _ = allow.check({"action": "CHANGE_DIRECTORY", "parameters": {"path": str(newdir)}, "risk": "low"})
        assert ok

    def test_restrictions_optional(self):
        allow = AllowList(actions=["RUN_COMMAND"])
        ok, _ = allow.check({"action": "RUN_COMMAND", "parameters": {"command": "anything --here"}, "risk": "high"})
        assert ok