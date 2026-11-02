from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

Clock = Callable[[], float]

APPROVAL_KIND_1 = "approval_1"
APPROVAL_KIND_2 = "approval_2"


@dataclass
class PendingApproval:
    request_id: str
    kind: str
    payload: dict
    created_at: float
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class ApprovalStore:
    """Tracks pending approvals with a TTL; auto-expires stale ones.

    Thread-safe. The clock is injectable for deterministic tests.
    """

    def __init__(self, ttl_seconds: int = 180, *, clock: Clock = time.time):
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._items: dict[str, PendingApproval] = {}
        self._lock = threading.RLock()

    def add(self, request_id: str, kind: str, payload: dict) -> PendingApproval:
        now = self._clock()
        approval = PendingApproval(
            request_id=request_id,
            kind=kind,
            payload=dict(payload),
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._items[request_id] = approval
        return approval

    def get(self, request_id: str) -> PendingApproval | None:
        with self._lock:
            return self._items.get(request_id)

    def resolve(self, request_id: str) -> PendingApproval | None:
        """Remove and return an approval (on APPROVE/DISAPPROVE/CANCEL)."""
        with self._lock:
            return self._items.pop(request_id, None)

    def expire_due(self) -> list[PendingApproval]:
        """Remove expired approvals (optionally pass frozen clock) and return them."""
        now = self._clock()
        expired: list[PendingApproval] = []
        with self._lock:
            for rid, item in list(self._items.items()):
                if now >= item.expires_at:
                    expired.append(self._items.pop(rid))
        return expired

    def pending_count(self) -> int:
        with self._lock:
            return len(self._items)

    def pending_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._items)