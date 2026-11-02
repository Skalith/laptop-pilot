from __future__ import annotations


class SenderAuth:
    """Authorized-sender allow-list (Telegram user IDs)."""

    def __init__(self, allowed_user_ids: set[int]):
        self._allowed = set(allowed_user_ids)

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self._allowed

    @property
    def allowed(self) -> list[int]:
        return sorted(self._allowed)