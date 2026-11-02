from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Common interface every provider adapter implements.

    Implementations parse the provider response into a Python dict
    (assumed to be JSON-shaped) and raise LLMProviderError on any failure.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier, e.g. 'gemini'."""

    @abstractmethod
    def generate_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Return the model's response parsed as a JSON dict."""