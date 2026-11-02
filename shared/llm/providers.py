from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .base import LLMProvider
from .errors import LLMProviderError


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` fences if a model wraps its answer in them."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return fence.group(1).strip() if fence else text


def _parse_json(text: str) -> dict:
    try:
        parsed = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMProviderError(f"Response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMProviderError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


@dataclass
class OpenAICompatibleProvider(LLMProvider):
    """Base adapter for OpenAI-compatible chat-completions endpoints.

    Used by Groq, NVIDIA (NIM) and Omniroute — they share the same wire format.
    """

    provider_name: str
    api_key: str
    base_url: str
    model: str
    json_mode: bool = True

    @property
    def name(self) -> str:
        return self.provider_name

    def generate_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - env dependency
            raise LLMProviderError("openai package not installed") from exc

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            kwargs: dict = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
            }
            if self.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            completion = client.chat.completions.create(**kwargs)
            content = completion.choices[0].message.content or ""
            return _parse_json(content)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"{self.provider_name} call failed: {exc}") from exc


@dataclass
class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile", base_url: str = "https://api.groq.com/openai/v1"):
        super().__init__(provider_name="groq", api_key=api_key, base_url=base_url, model=model)


@dataclass
class NVIDIAProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str = "meta/llama-3.3-70b-instruct", base_url: str = "https://integrate.api.nvidia.com/v1"):
        super().__init__(provider_name="nvidia", api_key=api_key, base_url=base_url, model=model)


@dataclass
class OmnirouteProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str, model: str = "openai/gpt-4o-mini"):
        super().__init__(provider_name="omniroute", api_key=api_key, base_url=base_url, model=model)


@dataclass
class GeminiProvider(LLMProvider):
    api_key: str
    model: str = "gemini-2.5-flash"
    json_mode: bool = True

    @property
    def name(self) -> str:
        return "gemini"

    def generate_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - env dependency
            raise LLMProviderError("google-genai package not installed") from exc

        try:
            client = genai.Client(api_key=self.api_key)
            config = None
            if self.json_mode:
                config = genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                )
            response = client.models.generate_content(
                model=self.model,
                contents=user,
                config=config,
            )
            return _parse_json(response.text)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"gemini call failed: {exc}") from exc