from __future__ import annotations

import logging
from typing import Callable

from .base import LLMProvider
from .errors import AllProvidersFailed

logger = logging.getLogger(__name__)

SwitchCallback = Callable[[str, Exception], None]


class FallbackRouter(LLMProvider):
    """Automatically tries providers in order; on failure switches to the next.

    Records which provider actually served the last call so consumers can
    surface it (audit log / Langfuse) as an LLM_PROVIDER_SWITCH event.
    """

    def __init__(
        self,
        providers: list[LLMProvider],
        *,
        on_switch: SwitchCallback | None = None,
    ):
        if not providers:
            raise ValueError("FallbackRouter requires at least one provider")
        self.providers = list(providers)
        self._on_switch = on_switch
        self._last_served: str | None = None

    @property
    def name(self) -> str:
        return "fallback[" + ",".join(provider.name for provider in self.providers) + "]"

    @property
    def last_served(self) -> str | None:
        """Name of the provider that served the most recent successful call."""
        return self._last_served

    def generate_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        attempts: list[tuple[str, Exception]] = []
        last_error: Exception | None = None

        for provider in self.providers:
            try:
                result = provider.generate_json(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                )
                if self._last_served != provider.name:
                    logger.info("LLM served by provider: %s", provider.name)
                self._last_served = provider.name
                return result
            except Exception as exc:
                self._last_served = None
                attempts.append((provider.name, exc))
                logger.warning(
                    "LLM provider '%s' failed (%d/%d): %s",
                    provider.name,
                    len(attempts),
                    len(self.providers),
                    exc,
                )
                if self._on_switch:
                    try:
                        self._on_switch(provider.name, exc)
                    except Exception as callback_error:  # never let tracing break failover
                        logger.exception("on_switch callback failed: %s", callback_error)
                last_error = exc

        raise AllProvidersFailed(attempts) from last_error