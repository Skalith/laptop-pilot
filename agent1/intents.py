from __future__ import annotations

import json

from shared.action_schema import Action

SYSTEM_PROMPT = (
    "You are Agent 1 of a remote laptop-control system. "
    "Convert the user's natural-language request into a JSON object with a single key "
    "\"commands\" holding an ordered list of commands. Each command MUST have exactly three fields: "
    "\"action\" — one of " + ", ".join(f'"{a.value}"' for a in Action) + "; "
    "\"parameters\" — an object with action-specific fields; "
    "\"risk\" — one of \"low\", \"medium\", \"high\". "
    "Use the absolute/current paths implied by the session context. "
    "Respond with ONLY valid JSON. No prose, no markdown, no trailing text."
)


def build_prompt(request: str, session_context: dict) -> tuple[str, str]:
    """Return (system, user) prompt strings for the LLM."""
    system = SYSTEM_PROMPT
    user = json.dumps({"request": request, "session_context": session_context}, ensure_ascii=False)
    return system, user


def build_repair_prompt(request: str, session_context: dict, original: dict, errors: list[str]) -> tuple[str, str]:
    """Return a repaired-prompt when the first answer failed schema validation."""
    system = SYSTEM_PROMPT
    user_parts = {
        "request": request,
        "session_context": session_context,
        "previous_attempt": original,
        "validation_errors": errors,
        "instruction": "Your previous answer was invalid. Return a corrected JSON object under \"commands\".",
    }
    return system, json.dumps(user_parts, ensure_ascii=False)