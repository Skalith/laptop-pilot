from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("shared.tracing.langfuse")


class _NullSpan:
    def __init__(self, name: str, metadata: dict | None = None):
        self.name = name
        self.metadata = metadata or {}

    def set_metadata(self, **kwargs: Any) -> "_NullSpan":
        self.metadata.update(kwargs)
        return self

    def set_output(self, **kwargs: Any) -> "_NullSpan":
        return self

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *exc) -> None:
        return None


class _NullTrace:
    def __init__(self, request_id: str, user_id: int | str | None = None):
        self.request_id = request_id
        self.user_id = user_id

    def span(self, name: str, **metadata: Any) -> _NullSpan:
        return _NullSpan(name, metadata)

    def end(self) -> None:
        return None


def _creds() -> tuple[str, str, str]:
    return (
        os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        os.getenv("LANGFUSE_SECRET_KEY", ""),
        os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )


def tracing_enabled() -> bool:
    public_key, secret_key, _ = _creds()
    return bool(public_key and secret_key)


class _LangfuseClient:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            from langfuse import Langfuse

            public_key, secret_key, host = _creds()
            cls._instance = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return cls._instance


class _LangfuseTrace:
    def __init__(self, request_id: str, user_id: int | str | None = None):
        self.request_id = request_id
        self._trace = _LangfuseClient.get().trace(
            id=request_id,
            name="lappilot_request",
            user_id=str(user_id) if user_id is not None else None,
        )

    def span(self, name: str, **metadata: Any):
        span = self._trace.span(name=name, metadata=metadata or None)
        return span

    def end(self) -> None:
        try:
            self._trace.end()
        except Exception as exc:  # never break the app because of tracing
            logger.debug("end trace failed: %s", exc)


def start_trace(request_id: str, user_id: int | str | None = None):
    """Start a top-level trace for one request; no-op when Langfuse isn't configured."""
    if tracing_enabled():
        try:
            return _LangfuseTrace(request_id, user_id)
        except Exception as exc:
            logger.warning("langfuse unavailable, falling back to null tracer: %s", exc)
    return _NullTrace(request_id, user_id)


def span_llm_call(trace, *, provider: str | None, model: str | None = None, max_tokens: int | None = None):
    """Span for a single LLM call inside an active trace."""
    if trace is None:
        return _NullSpan("llm_call", {"provider": provider, "model": model})
    return trace.span(
        "llm_call",
        provider=provider,
        model=model,
        max_tokens=max_tokens,
    )


def span_provider_switch(trace, *, failed_provider: str, error: str, next_provider: str | None = None):
    """Log an LLM_PROVIDER_SWITCH event."""
    if trace is None:
        return _NullSpan("LLM_PROVIDER_SWITCH", {"failed_provider": failed_provider})
    return trace.span(
        "LLM_PROVIDER_SWITCH",
        failed_provider=failed_provider,
        next_provider=next_provider,
        error=str(error)[:500],
    )