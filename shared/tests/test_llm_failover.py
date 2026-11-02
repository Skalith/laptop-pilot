from __future__ import annotations

import pytest

from shared.llm.base import LLMProvider
from shared.llm.errors import AllProvidersFailed
from shared.llm.failover import FallbackRouter


class FakeProvider(LLMProvider):
    def __init__(self, name: str, *, raise_on_call: bool = False):
        self._name = name
        self.raise_on_call = raise_on_call
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        self.calls += 1
        if self.raise_on_call:
            raise RuntimeError(f"{self._name} exploded")
        return {"provider": self._name, "system": system, "user": user}


class TestFallbackRouter:
    def test_first_healthy_provider_serves_the_call(self):
        ok = FakeProvider("ok")
        router = FallbackRouter([ok])
        result = router.generate_json(system="s", user="u")
        assert result["provider"] == "ok"
        assert router.last_served == "ok"

    def test_automatically_switches_to_next_provider_on_failure(self):
        broken = FakeProvider("broken", raise_on_call=True)
        ok = FakeProvider("ok")
        router = FallbackRouter([broken, ok])

        result = router.generate_json(system="s", user="u")

        assert broken.calls == 1
        assert ok.calls == 1
        assert result["provider"] == "ok"
        assert router.last_served == "ok"

    def test_switches_multiple_times_until_success(self):
        broken1 = FakeProvider("b1", raise_on_call=True)
        broken2 = FakeProvider("b2", raise_on_call=True)
        ok = FakeProvider("ok")
        router = FallbackRouter([broken1, broken2, ok])

        result = router.generate_json(system="s", user="u")

        assert result["provider"] == "ok"
        assert router.last_served == "ok"

    def test_all_providers_down_raises_clear_error(self):
        broken1 = FakeProvider("b1", raise_on_call=True)
        broken2 = FakeProvider("b2", raise_on_call=True)
        router = FallbackRouter([broken1, broken2])

        with pytest.raises(AllProvidersFailed) as exc_info:
            router.generate_json(system="s", user="u")

        assert [name for name, _ in exc_info.value.attempts] == ["b1", "b2"]
        assert router.last_served is None

    def test_on_switch_callback_reports_failed_provider(self):
        events: list[str] = []
        broken = FakeProvider("broken", raise_on_call=True)
        ok = FakeProvider("ok")
        router = FallbackRouter([broken, ok], on_switch=lambda name, err: events.append(name))

        router.generate_json(system="s", user="u")

        assert events == ["broken"]

    def test_on_switch_callback_failure_does_not_break_failover(self):
        broken = FakeProvider("broken", raise_on_call=True)
        ok = FakeProvider("ok")

        def bad_callback(name, err):
            raise AssertionError("callback bug")

        router = FallbackRouter([broken, ok], on_switch=bad_callback)
        result = router.generate_json(system="s", user="u")
        assert result["provider"] == "ok"

    def test_forwards_max_tokens_to_provider(self):
        provider = FakeProvider("ok")
        router = FallbackRouter([provider])
        router.generate_json(system="s", user="u", max_tokens=512)
        assert provider.calls == 1

    def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError):
            FallbackRouter([])

    def test_resets_last_served_after_failure_then_sets_on_success(self):
        broken = FakeProvider("broken", raise_on_call=True)
        ok = FakeProvider("ok")
        router = FallbackRouter([broken, ok])
        router.generate_json(system="s", user="u")
        assert router.last_served == "ok"