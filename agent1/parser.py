from __future__ import annotations

import json
import re


class ParseError(Exception):
    """Raised when the LLM response cannot be parsed into a command list."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return fence.group(1).strip() if fence else text


def extract_json(payload: object) -> dict:
    """Extract a JSON dict from the LLM response object."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(_strip_fences(payload))
            if not isinstance(parsed, dict):
                raise ParseError(f"expected JSON object, got {type(parsed).__name__}")
            return parsed
        except json.JSONDecodeError as exc:
            raise ParseError(f"response was not valid JSON: {exc}") from exc
    raise ParseError(f"unexpected LLM payload type: {type(payload).__name__}")


def parse_commands(payload: object) -> list[dict]:
    """Extract the list of command dicts. Accepts {"commands": [...]} or a bare list."""
    if isinstance(payload, list):
        data: object = payload
    else:
        data = extract_json(payload)

    if isinstance(data, dict):
        commands = data.get("commands")
    elif isinstance(data, list):
        commands = data
    else:
        raise ParseError(f"expected a list or object, got {type(data).__name__}")

    if commands is None:
        raise ParseError("payload has no 'commands' list")
    if not isinstance(commands, list):
        raise ParseError("'commands' must be a list")

    result = []
    for item in commands:
        if not isinstance(item, dict):
            raise ParseError(f"command entry is not an object: {item!r}")
        result.append(item)
    return result