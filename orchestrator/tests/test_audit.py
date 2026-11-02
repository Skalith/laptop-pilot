import re

from shared.messages import EventType
from orchestrator.audit import AuditLogger


class TestAuditLogger:
    def test_logs_expected_line_format(self, tmp_path):
        log = AuditLogger(str(tmp_path / "audit.log"))
        log.log(EventType.REQUEST_RECEIVED, "111", "open vscode")

        lines = log.read()
        assert len(lines) == 1
        match = re.match(
            r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[REQUEST_RECEIVED\] \[111\] \[open vscode\]$",
            lines[0],
        )
        assert match is not None

    def test_appends_multiple_entries_in_order(self, tmp_path):
        log = AuditLogger(str(tmp_path / "audit.log"))
        log.log(EventType.COMMAND_GENERATED, "111", "one")
        log.log(EventType.APPROVAL_1_SENT, "111", "two")
        lines = log.read()
        assert len(lines) == 2
        assert "APPROVAL_1_SENT" in lines[1]
        assert "APPROVAL_1_SENT" not in lines[0]

    def test_read_missing_file_returns_empty(self, tmp_path):
        log = AuditLogger(str(tmp_path / "nope.log"))
        assert log.read() == []

    def test_clear_removes_file(self, tmp_path):
        log = AuditLogger(str(tmp_path / "audit.log"))
        log.log(EventType.ERROR, "", "boom")
        assert len(log.read()) == 1
        log.clear()
        assert log.read() == []