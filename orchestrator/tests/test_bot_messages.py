from __future__ import annotations

import pytest

from orchestrator.bot import messages


class TestTextBuilders:
    def test_approval_one_text_contains_details(self):
        text = messages.approval_one_text(
            "r1",
            [{"action": "RUN_COMMAND", "parameters": {"command": "ls"}, "risk": "high"}, {"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}],
            "high",
        )
        assert "Approval #1" in text
        assert "r1" in text
        assert "RUN_COMMAND" in text
        assert "TAKE_SCREENSHOT" in text
        assert "HIGH" in text

    def test_approval_two_text_has_steps(self):
        text = messages.approval_two_text("r2", ["Run 'cd /tmp'", "Verify directory"], "medium")
        assert "Approval #2" in text
        assert "cd /tmp" in text
        assert "MEDIUM" in text

    def test_result_text_includes_output_and_cwd(self):
        result = {
            "results": [{"name": "ls", "status": "ok", "output": "file1"}],
            "cwd": "/home/u",
        }
        text = messages.result_text(result)
        assert "file1" in text
        assert "/home/u" in text

    def test_error_text(self):
        assert "boom" in messages.error_text("boom")


class TestCallbacks:
    def test_parse_roundtrip(self):
        assert messages.parse_callback_data("approve1:abc") == ("approve", 1, "abc")
        assert messages.parse_callback_data("disapprove1:abc") == ("disapprove", 1, "abc")
        assert messages.parse_callback_data("execute2:xyz") == ("execute", 2, "xyz")
        assert messages.parse_callback_data("cancel2:xyz") == ("cancel", 2, "xyz")

    def test_parse_rejects_unknown(self):
        with pytest.raises(ValueError):
            messages.parse_callback_data("nuke3:abc")
        with pytest.raises(ValueError):
            messages.parse_callback_data("approve1:")


class TestKeyboards:
    def test_approval_one_buttons(self):
        kb = messages.approval_one_keyboard("rid")
        labels = [b.text for row in kb.inline_keyboard for b in row]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert labels == ["APPROVE", "DISAPPROVE"]
        assert data == ["approve1:rid", "disapprove1:rid"]

    def test_approval_two_buttons(self):
        kb = messages.approval_two_keyboard("rid")
        labels = [b.text for row in kb.inline_keyboard for b in row]
        assert labels == ["EXECUTE", "CANCEL"]