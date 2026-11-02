from __future__ import annotations

from typing import Callable

from .base import LLMProvider
from .errors import LLMProviderError
from .failover import FallbackRouter, SwitchCallback
from .providers import (
    GeminiProvider,
    GroqProvider,
    NVIDIAProvider,
    OmnirouteProvider,
)

PROVIDER_ORDER_DEFAULT = "gemini,groq,nvidia,omniroute"

ProviderBuilder = Callable[[dict], LLMProvider]


def _build_gemini(config: dict) -> GeminiProvider:
    return GeminiProvider(
        api_key=_require(config, "GEMINI_API_KEY"),
        model=config.get("GEMINI_MODEL", "gemini-2.5-flash"),
        json_mode=_as_bool(config.get("GEMINI_JSON_MODE", "true")),
    )


def _build_groq(config: dict) -> GroqProvider:
    return GroqProvider(
        api_key=_require(config, "GROQ_API_KEY"),
        model=config.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        base_url=config.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    )


def _build_nvidia(config: dict) -> NVIDIAProvider:
    return NVIDIAProvider(
        api_key=_require(config, "NVIDIA_API_KEY"),
        model=config.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
        base_url=config.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    )


def _build_omniroute(config: dict) -> OmnirouteProvider:
    return OmnirouteProvider(
        api_key=_require(config, "OMNIROUTE_API_KEY"),
        base_url=_require(config, "OMNIROUTE_BASE_URL"),
        model=config.get("OMNIROUTE_MODEL", "openai/gpt-4o-mini"),
    )


_BUILDERS: dict[str, ProviderBuilder] = {
    "gemini": _build_gemini,
    "groq": _build_groq,
    "nvidia": _build_nvidia,
    "omniroute": _build_omniroute,
}


def create_llm(config: dict, *, on_switch: SwitchCallback | None = None) -> LLMProvider:
    """Factory Method: build the ordered provider chain and wrap it in failover.

    Returns a single LLMProvider regardless of how many providers are configured.
    Fails fast (raises LLMProviderError) if any configured provider is unknown or
    missing its required key — the chain never silently skips a provider.
    """
    order_raw = config.get("LLM_PROVIDER_ORDER") or PROVIDER_ORDER_DEFAULT
    if isinstance(order_raw, str):
        order = [name.strip().lower() for name in order_raw.split(",") if name.strip()]
    else:
        order = [str(name).strip().lower() for name in order_raw if str(name).strip()]

    if not order:
        raise LLMProviderError("LLM_PROVIDER_ORDER produced an empty provider list")

    fallback_enabled = _as_bool(config.get("LLM_FALLBACK_ENABLED", "true"))

    providers: list[LLMProvider] = []
    for name in order:
        builder = _BUILDERS.get(name)
        if builder is None:
            raise LLMProviderError(f"Unknown LLM provider: {name}")
        providers.append(builder(config))

    if fallback_enabled and len(providers) > 1:
        return FallbackRouter(providers, on_switch=on_switch)
    return providers[0]


def _require(config: dict, key: str) -> str:
    """Fail fast when a required config key is missing or empty."""
    value = config.get(key)
    if not value or not str(value).strip():
        raise LLMProviderError(f"Missing required config: {key}")
    return str(value).strip()


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}