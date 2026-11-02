from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path


class AuditLogger:
    """Append-only audit log.

    Format: [TIMESTAMP] [EVENT_TYPE] [USER_ID] [DETAILS]
    """

    def __init__(self, log_path: str = "./logs/audit.log"):
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = Path(log_path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event_type: str, user_id: str = "", details: str = "") -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{event_type}] [{user_id}] [{details}]\n"
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())

    def read(self) -> list[str]:
        """Read all log lines (used by tests / inspection)."""
        with self._lock:
            if not self._path.exists():
                return []
            return self._path.read_text(encoding="utf-8").splitlines()

    def clear(self) -> None:
        with self._lock:
            if self._path.exists():
                self._path.unlink()