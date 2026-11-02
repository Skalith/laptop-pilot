from __future__ import annotations

import os
import tempfile

from agent2.executor import Executor


class TestExecutor:
    def test_change_directory_via_executor(self):
        with tempfile.TemporaryDirectory() as workdir:
            with Executor() as exec_:
                result = exec_.run(
                    {"action": "CHANGE_DIRECTORY", "parameters": {"path": workdir}, "risk": "low"}
                )
                assert result["status"] == "ok"
                assert exec_.shell.cwd == os.path.realpath(workdir)

    def test_run_command_via_executor(self):
        with Executor() as exec_:
            result = exec_.run({"action": "RUN_COMMAND", "parameters": {"command": "echo via-exec"}, "risk": "high"})
            assert result["status"] == "ok"
            assert "via-exec" in result["output"]

    def test_file_write_read_delete(self):
        with tempfile.TemporaryDirectory() as workdir:
            target = os.path.join(workdir, "note.txt")
            with Executor() as exec_:
                written = exec_.run(
                    {"action": "FILE_OPERATION", "parameters": {"operation": "write", "path": target, "content": "data-123"}, "risk": "medium"}
                )
                assert written["status"] == "ok"
                read = exec_.run({"action": "FILE_OPERATION", "parameters": {"operation": "read", "path": target}, "risk": "low"})
                assert "data-123" in read["output"]
                deleted = exec_.run(
                    {"action": "FILE_OPERATION", "parameters": {"operation": "delete", "path": target}, "risk": "high"}
                )
                assert deleted["status"] == "ok"
                assert not os.path.exists(target)

    def test_screenshot_via_executor(self):
        with Executor() as exec_:
            result = exec_.run({"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"})
            assert result["status"] == "ok"
            assert result["mime"] == "image/png"

    def test_execute_all_aggregates(self):
        with tempfile.TemporaryDirectory() as workdir:
            commands = [
                {"action": "CHANGE_DIRECTORY", "parameters": {"path": workdir}, "risk": "low"},
                {"action": "RUN_COMMAND", "parameters": {"command": "echo done"}, "risk": "high"},
            ]
            with Executor() as exec_:
                outcome = exec_.execute_all(commands)
            assert outcome["status"] == "ok"
            assert len(outcome["results"]) == 2
            assert outcome["cwd"] == os.path.realpath(workdir)

    def test_execute_all_reports_failure(self):
        with Executor() as exec_:
            outcome = exec_.execute_all(
                [{"action": "RUN_COMMAND", "parameters": {"command": "bash -c 'exit 4'"}, "risk": "high"}]
            )
        assert outcome["status"] == "error"
        assert outcome["error"] is not None