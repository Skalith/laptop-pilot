from __future__ import annotations

from agent2.planner import plan_for_command


class TestPlanner:
    def test_change_directory_plan(self):
        steps = plan_for_command({"action": "CHANGE_DIRECTORY", "parameters": {"path": "~/backend"}, "risk": "low"})
        assert any("cd ~/backend" in step for step in steps)
        assert any("verify" in step.lower() for step in steps)

    def test_open_application_plan_is_concrete(self):
        steps = plan_for_command(
            {"action": "OPEN_APPLICATION", "parameters": {"application": "vscode", "target": "~/backend"}, "risk": "low"}
        )
        assert steps[0].startswith("Check")
        assert any("launch" in s.lower() and "vscode" in s.lower() for s in steps)
        assert len(steps) >= 3

    def test_run_command_plan(self):
        steps = plan_for_command({"action": "RUN_COMMAND", "parameters": {"command": "ls -la"}, "risk": "high"})
        assert any("ls -la" in step for step in steps)
        assert any("exit code" in step for step in steps)

    def test_file_delete_plan(self):
        steps = plan_for_command(
            {"action": "FILE_OPERATION", "parameters": {"operation": "delete", "path": "~/x.txt"}, "risk": "high"}
        )
        assert any("delete" in s.lower() and "~/x.txt" in s for s in steps)

    def test_screenshot_plan(self):
        steps = plan_for_command({"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"})
        assert any("screen" in step.lower() for step in steps)

    def test_unknown_action_still_yields_plan(self):
        steps = plan_for_command({"action": "FANCY_THING", "parameters": {"x": 1}, "risk": "high"})
        assert steps and "FANCY_THING" in steps[0]