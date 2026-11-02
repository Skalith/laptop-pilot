from __future__ import annotations


class LLMProviderError(Exception):
    """A single LLM provider call failed (network, auth, parse, ...)."""


class AllProvidersFailed(Exception):
    """Every provider in the failover chain failed."""

    def __init__(self, attempts: list[tuple[str, Exception]]):
        self.attempts = attempts
        detail = "; ".join(f"{name}: {err}" for name, err in attempts)
        super().__init__(f"All LLM providers failed: {detail}")