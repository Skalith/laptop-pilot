from __future__ import annotations

import os
import tempfile

from agent2.executor.terminal import PersistentShell


class TestPersistentShell:
    def test_runs_command_and_captures_output(self):
        with PersistentShell() as shell:
            result = shell.run("echo hello world")
        assert result.exit_code == 0
        assert result.output == "hello world"

    def test_captures_non_zero_exit_code(self):
        with PersistentShell() as shell:
            result = shell.run("bash -c 'exit 7'")
        assert result.exit_code == 7

    def test_false_returns_1(self):
        with PersistentShell() as shell:
            result = shell.run("false")
        assert result.exit_code == 1

    def test_cwd_is_a_real_directory(self):
        with PersistentShell() as shell:
            assert os.path.isabs(shell.cwd) and os.path.isdir(shell.cwd)

    def test_change_directory_updates_persistent_cwd(self):
        with tempfile.TemporaryDirectory() as workdir:
            with PersistentShell() as shell:
                result = shell.change_directory(workdir)
                assert result.exit_code == 0
                assert shell.cwd == os.path.realpath(workdir)
                pwd = shell.run("pwd")
                assert pwd.output.strip() == os.path.realpath(workdir)

    def test_cwd_persists_across_commands(self):
        with tempfile.TemporaryDirectory() as workdir:
            with PersistentShell() as shell:
                shell.run(f"cd {workdir}")
                second = shell.run("pwd")
                third = shell.run("pwd")
                assert second.output.strip() == os.path.realpath(workdir)
                assert third.output.strip() == os.path.realpath(workdir)

    def test_exports_persist_across_commands(self):
        with PersistentShell() as shell:
            shell.run("export LP_TEST_VAR=42")
            result = shell.run("echo $LP_TEST_VAR")
        assert result.output.strip() == "42"