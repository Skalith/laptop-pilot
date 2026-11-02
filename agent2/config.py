from __future__ import annotations

import os
from dataclasses import dataclass, field


DEFAULT_ALLOWLIST = {
    "actions": [
        "CHANGE_DIRECTORY",
        "OPEN_APPLICATION",
        "RUN_COMMAND",
        "FILE_OPERATION",
        "CLOSE_APPLICATION",
        "TAKE_SCREENSHOT",
    ],
    "paths": ["~/"],
    "applications": [],
    "commands": ["ls", "cd", "pwd", "cat", "echo", "mkdir", "touch"],
}


@dataclass
class Agent2Config:
    relay_url: str = "ws://localhost:8765"
    relay_secret: str = ""
    ws_path: str = "/ws/agent2"
    allowlist_path: str = "./config/allowlist.json"
    shell: str = "/bin/bash"
    reconnect_delay: float = 2.0
    screenshot_timeout: float = 5.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.relay_secret:
            errors.append("RELAY_SECRET")
        if not self.relay_url:
            errors.append("RELAY_URL")
        return errors

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Agent2Config":
        env = env if env is not None else os.environ
        return cls(
            relay_url=env.get("RELAY_URL", "ws://localhost:8765"),
            relay_secret=env.get("RELAY_SECRET", ""),
            allowlist_path=env.get("AGENT2_ALLOWLIST_PATH", "./config/allowlist.json"),
            shell=env.get("AGENT2_SHELL", "/bin/bash"),
            reconnect_delay=float(env.get("AGENT2_RECONNECT_DELAY", "2.0") or 2.0),
            screenshot_timeout=float(env.get("AGENT2_SCREENSHOT_TIMEOUT", "5.0") or 5.0),
        )