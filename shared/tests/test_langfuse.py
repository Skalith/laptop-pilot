from __future__ import annotations

import pytest

from shared.tracing import langfuse


class TestNullPath:
    def test_disabled_without_credentials(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        assert langfuse.tracing_enabled() is False

    def test_start_trace_returns_null_when_disabled(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        trace = langfuse.start_trace("r1", "111")
        assert isinstance(trace, langfuse._NullTrace)

    def test_null_spans_are_usable(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        trace = langfuse.start_trace("r1", "111")
        with trace.span("COMMAND_GENERATED", risk="high") as span:
            span.set_output(foo="bar")
        trace.end()


class TestSpanHelpers:
    def test_span_llm_call_and_switch(self):
        span = langfuse.span_llm_call(None, provider="gemini")
        assert span.name == "llm_call"
        switch = langfuse.span_provider_switch(None, failed_provider="gemini", error="boom", next_provider="groq")
        assert switch.name == "LLM_PROVIDER_SWITCH"


class FakeRanSpan:
    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class FakeBackend:
    def __init__(self):
        self.spans: list[str] = []

    def trace(self, *, id, name, user_id):
        self.spans.append(f"trace:{id}")
        return FakeTrace(self)


class FakeTrace:
    def __init__(self, backend):
        self.backend = backend

    def span(self, *, name, metadata=None):
        self.backend.spans.append(f"span:{name}")
        return FakeRanSpan(name, metadata)

    def end(self):
        self.backend.spans.append("end")


@pytest.fixture()
def fake_langfuse(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(langfuse._LangfuseClient, "get", classmethod(lambda cls: backend))
    langfuse._LangfuseClient._instance = backend
    return backend


class TestEnabledPath:
    def test_trace_records_spans(self, fake_langfuse):
        assert langfuse.tracing_enabled() is True
        trace = langfuse.start_trace("r1", "111")
        with trace.span("COMMAND_GENERATED", risk="low"):
            pass
        with trace.span("APPROVAL_1_RESULT", decision="approve"):
            pass
        trace.end()
        assert fake_langfuse.spans == ["trace:r1", "span:COMMAND_GENERATED", "span:APPROVAL_1_RESULT", "end"]

    def test_span_llm_call_records(self, fake_langfuse):
        trace = langfuse.start_trace("r1", "111")
        with langfuse.span_llm_call(trace, provider="groq"):
            pass
        assert "span:llm_call" in fake_langfuse.spans