import pytest

from shared.risk_classifier import classify_risk


class TestRiskClassifierLow:
    def test_change_directory_is_low(self):
        assert classify_risk("CHANGE_DIRECTORY", {"path": "~/projects"}) == "low"

    def test_open_known_application_is_low(self):
        assert classify_risk("OPEN_APPLICATION", {"application": "vscode"}) == "low"

    def test_take_screenshot_is_low(self):
        assert classify_risk("TAKE_SCREENSHOT", {}) == "low"

    def test_read_only_file_operation_is_low(self):
        assert classify_risk("FILE_OPERATION", {"operation": "read", "path": "~/x.txt"}) == "low"

    def test_read_only_command_is_low(self):
        assert classify_risk("RUN_COMMAND", {"command": "ls -la ~/projects"}) == "low"


class TestRiskClassifierMedium:
    def test_write_file_operation_is_medium(self):
        assert classify_risk("FILE_OPERATION", {"operation": "write", "path": "~/x.txt"}) == "medium"

    def test_save_file_operation_is_medium(self):
        assert classify_risk("FILE_OPERATION", {"operation": "save", "path": "~/x.txt"}) == "medium"

    def test_close_application_is_medium(self):
        assert classify_risk("CLOSE_APPLICATION", {"application": "firefox"}) == "medium"


class TestRiskClassifierHigh:
    def test_delete_file_is_high(self):
        assert classify_risk("FILE_OPERATION", {"operation": "delete", "path": "~/x.txt"}) == "high"

    def test_arbitrary_run_command_is_high(self):
        assert classify_risk("RUN_COMMAND", {"command": "rm -rf /tmp/x"}) == "high"

    def test_credential_touching_command_is_high(self):
        assert classify_risk("RUN_COMMAND", {"command": "sudo apt install docker"}) == "high"

    def test_unknown_action_defaults_to_high(self):
        assert classify_risk("DO_SOMETHING_WILD", {}) == "high"

    def test_unknown_file_operation_defaults_to_high(self):
        assert classify_risk("FILE_OPERATION", {"operation": "teleport"}) == "high"

    def test_open_unknown_application_is_high(self):
        assert classify_risk("OPEN_APPLICATION", {"application": "sketchy-mystery-app"}) == "high"