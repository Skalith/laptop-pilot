from __future__ import annotations

import pytest

from shared.llm.base import LLMProvider
from shared.llm.errors import LLMProviderError
from shared.llm.failover import FallbackRouter
from shared.llm.factory import create_llm

VALID_CONFIG = {
    "LLM_PROVIDER_ORDER": "gemini,groq,nvidia,omniroute",
    "LLM_FALLBACK_ENABLED": "true",
    "GEMINI_API_KEY": "g-key",
    "GROQ_API_KEY": "groq-key",
    "NVIDIA_API_KEY": "nv-key",
    "OMNIROUTE_API_KEY": "omni-key",
    "OMNIROUTE_BASE_URL": "https://omniroute.example.com/v1",
}


class TestFactoryShape:
    def test_factory_returns_fallback_router_for_multi_provider_chain(self):
        llm = create_llm(VALID_CONFIG)
        assert isinstance(llm, FallbackRouter)

    def test_factory_returns_single_provider_when_only_one_configured(self):
        cfg = dict(VALID_CONFIG, LLM_PROVIDER_ORDER="gemini")
        llm = create_llm(cfg)
        assert isinstance(llm, LLMProvider)
        assert not isinstance(llm, FallbackRouter)

    def test_fallback_disabled_returns_first_provider(self):
        cfg = dict(VALID_CONFIG, LLM_FALLBACK_ENABLED="false")
        llm = create_llm(cfg)
        assert isinstance(llm, LLMProvider)
        assert not isinstance(llm, FallbackRouter)


class TestFactoryFailFast:
    def test_unknown_provider_fails_fast(self):
        cfg = dict(VALID_CONFIG, LLM_PROVIDER_ORDER="claude")
        with pytest.raises(LLMProviderError, match="Unknown LLM provider"):
            create_llm(cfg)

    def test_missing_api_key_fails_fast(self):
        cfg = dict(VALID_CONFIG, GEMINI_API_KEY="")
        with pytest.raises(LLMProviderError, match="GEMINI_API_KEY"):
            create_llm(cfg)

    def test_empty_order_fails_fast(self):
        cfg = dict(VALID_CONFIG, LLM_PROVIDER_ORDER=",")
        with pytest.raises(LLMProviderError, match="empty provider list"):
            create_llm(cfg)

    def test_omniroute_requires_base_url(self):
        cfg = dict(VALID_CONFIG, OMNIROUTE_BASE_URL="")
        with pytest.raises(LLMProviderError, match="OMNIROUTE_BASE_URL"):
            create_llm(cfg)

    def test_individual_keys_are_not_checked_if_provider_not_in_order(self):
        cfg = dict(VALID_CONFIG, LLM_PROVIDER_ORDER="gemini", NVIDIA_API_KEY="")
        llm = create_llm(cfg)
        assert llm is not None