from __future__ import annotations

import os
from dataclasses import dataclass, field

LLM_KEY_FIELDS = (
    "LLM_PROVIDER_ORDER",
    "LLM_FALLBACK_ENABLED",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_BASE_URL",
    "NVIDIA_API_KEY",
    "NVIDIA_MODEL",
    "NVIDIA_BASE_URL",
    "OMNIROUTE_API_KEY",
    "OMNIROUTE_BASE_URL",
    "OMNIROUTE_MODEL",
)


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except (TypeError, ValueError):
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    telegram_bot_token: str = ""
    authorized_user_ids: set[int] = field(default_factory=set)
    relay_url: str = "ws://localhost:8765"
    relay_secret: str = ""
    approval_ttl_seconds: int = 180
    dispatch_timeout_seconds: int = 60
    auto_proceed_low_risk: bool = False
    log_path: str = "./logs/audit.log"
    llm: dict = field(default_factory=dict)  # forwarded to shared.llm.factory.create_llm

    def validate(self) -> list[str]:
        """Return a list of missing-required-config errors (empty when OK)."""
        errors: list[str] = []
        if not self.authorized_user_ids:
            errors.append("AUTHORIZED_USER_ID")
        if not self.relay_secret:
            errors.append("RELAY_SECRET")
        if not self.relay_url:
            errors.append("RELAY_URL")
        return errors

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        env = env if env is not None else os.environ
        ids: set[int] = set()
        for raw in env.get("AUTHORIZED_USER_ID", "").split(","):
            raw = raw.strip()
            if raw:
                try:
                    ids.add(int(raw))
                except ValueError:
                    pass
        llm = {}
        for key in LLM_KEY_FIELDS:
            if env.get(key):
                llm[key] = env[key]
        return cls(
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
            authorized_user_ids=ids,
            relay_url=env.get("RELAY_URL", "ws://localhost:8765"),
            relay_secret=env.get("RELAY_SECRET", ""),
            approval_ttl_seconds=_as_int(env.get("APPROVAL_TTL_SECONDS"), 180),
            dispatch_timeout_seconds=_as_int(env.get("DISPATCH_TIMEOUT_SECONDS"), 60),
            auto_proceed_low_risk=_as_bool(env.get("AUTO_PROCEED_LOW_RISK"), False),
            log_path=env.get("LOG_PATH", "./logs/audit.log"),
            llm=llm,
        )