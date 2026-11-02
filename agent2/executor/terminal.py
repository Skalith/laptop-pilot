from __future__ import annotations

import os
import select
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass
class ShellResult:
    exit_code: int
    output: str


class PersistentShell:
    """A long-lived bash session kept alive across commands.

    Uses a non-interactive ``bash -s`` reading from a pipe: the same process
    persists across commands, so CWD and exported state are preserved. There is
    no PTY echo to parse away; reads are synchronized with a sentinel token.
    """

    _EXIT_PREFIX = "_LP_EXIT_"

    def __init__(self, shell: str = "/bin/bash", timeout: float = 6.0):
        self.shell = shell
        self.timeout = timeout
        env = {**os.environ, "PS1": "x", "PS2": "", "PROMPT_COMMAND": ""}
        self._proc = subprocess.Popen(
            [shell, "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self._cwd = os.getcwd()
        result = self._execute("pwd")
        clean = result.output.strip()
        if clean:
            self._cwd = clean

    # -- internals -------------------------------------------------------

    def _write(self, data: str) -> None:
        if self._proc.poll() is not None:
            raise RuntimeError("shell process has exited")
        self._proc.stdin.write(data.encode())
        self._proc.stdin.flush()

    def _read_until(self, token: str) -> str:
        deadline = time.monotonic() + self.timeout
        buffer = ""
        fd = self._proc.stdout.fileno()
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([fd], [], [], remaining)
            if fd not in ready:
                break
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk.decode(errors="replace")
            if token in buffer:
                return buffer
        raise TimeoutError(f"timed out waiting for '{token}' in shell output")

    def _drain(self, delay: float = 0.03) -> None:
        """Swallow any trailing bytes that arrived after the sentinel."""
        time.sleep(delay)
        fd = self._proc.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if fd not in ready:
                return
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return
            if not chunk:
                return

    # -- public API ------------------------------------------------------

    def _execute(self, command: str) -> ShellResult:
        sentinel = f"{self._EXIT_PREFIX}{os.getpid()}_{self._master_id}_"
        self._write(f"{command}\n")
        self._write(f"printf \"\\n{sentinel}$?\\n\"\n")
        stream = self._read_until(sentinel)
        head, _, tail = stream.partition(sentinel)
        code = 1
        if tail.strip():
            try:
                code = int(tail.strip().splitlines()[0].strip())
            except ValueError:
                code = 1
        self._drain()
        return ShellResult(exit_code=code, output=head.strip())

    @property
    def _master_id(self) -> int:
        return self._proc.pid

    def run(self, command: str) -> ShellResult:
        result = self._execute(command)
        if command.strip().startswith("cd "):
            self._cwd = self._current_pwd()
        return result

    def change_directory(self, path: str) -> ShellResult:
        result = self.run(f"cd {path}")
        self._cwd = self._current_pwd()
        return result

    def _current_pwd(self) -> str:
        result = self._execute("pwd")
        clean = result.output.strip()
        return clean or self._cwd

    @property
    def cwd(self) -> str:
        return self._cwd

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        except ProcessLookupError:
            pass
        for stream in (self._proc.stdout, self._proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> "PersistentShell":
        return self

    def __exit__(self, *exc) -> None:
        self.close()