import pytest

from shared.action_schema import Action, Command, Risk, validate_command


class TestValidateCommand:
    def test_valid_command_returns_true_none(self):
        cmd = {
            "action": "CHANGE_DIRECTORY",
            "parameters": {"path": "~/projects"},
            "risk": "low",
        }
        assert validate_command(cmd) == (True, None)

    def test_valid_command_object_returns_true_none(self):
        cmd = Command(
            action=Action.OPEN_APPLICATION,
            parameters={"application": "vscode"},
            risk=Risk.LOW,
        )
        assert validate_command(cmd) == (True, None)

    def test_missing_risk_fails(self):
        cmd = {"action": "CHANGE_DIRECTORY", "parameters": {"path": "~/"}}
        valid, err = validate_command(cmd)
        assert valid is False
        assert err is not None
        assert "risk" in err

    def test_unknown_action_fails(self):
        cmd = {"action": "DO_THE_THING", "parameters": {}, "risk": "low"}
        valid, err = validate_command(cmd)
        assert valid is False
        assert err is not None
        assert "DO_THE_THING" in err

    def test_missing_action_fails(self):
        cmd = {"parameters": {"path": "~/"}, "risk": "low"}
        valid, err = validate_command(cmd)
        assert valid is False
        assert "action" in err

    def test_invalid_risk_value_fails(self):
        cmd = {"action": "RUN_COMMAND", "parameters": {"command": "ls"}, "risk": "severe"}
        valid, err = validate_command(cmd)
        assert valid is False
        assert "risk" in err

    def test_invalid_parameters_type_fails(self):
        cmd = {"action": "CHANGE_DIRECTORY", "parameters": "not-a-dict", "risk": "low"}
        valid, err = validate_command(cmd)
        assert valid is False
        assert err is not None

    def test_empty_parameters_is_valid(self):
        cmd = {"action": "TAKE_SCREENSHOT", "risk": "low"}
        assert validate_command(cmd) == (True, None)

    def test_all_valid_actions_pass(self):
        valid_cmds = [
            {"action": a.value, "parameters": {}, "risk": "low"}
            for a in Action
        ]
        for cmd in valid_cmds:
            assert validate_command(cmd) == (True, None), cmd