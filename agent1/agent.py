from __future__ import annotations

import logging
from typing import Any

from shared.action_schema import validate_command
from shared.risk_classifier import classify_risk
from shared.tracing.langfuse import span_llm_call

from . import intents, parser

logger = logging.getLogger("agent1")


class LLMValidationError(Exception):
    """Agent 1 could not produce a schema-valid command list."""


class Agent1:
    """AI / Remote Agent: natural language -> validated, risk-classified command list.

    Consumes any LLMProvider (single or failover router) built by shared.llm.factory.
    """

    def __init__(self, llm: Any, *, max_repair_attempts: int = 1):
        self.llm = llm
        self.max_repair_attempts = max_repair_attempts

    def generate_commands(self, request: str, session_context: dict, *, trace=None) -> list[dict]:
        system, user = intents.build_prompt(request, session_context)
        provider = getattr(self.llm, "last_served", None) or getattr(self.llm, "name", None)
        with span_llm_call(trace, provider=provider):
            payload = self.llm.generate_json(system=system, user=user)
        commands, errors = self._parse_and_validate(payload)

        if errors and self.max_repair_attempts > 0:
            logger.info("repairing invalid Agent 1 output: %s", errors)
            repair_system, repair_user = intents.build_repair_prompt(request, session_context, payload, errors)
            with span_llm_call(trace, provider=provider, model="repair"):
                repaired = self.llm.generate_json(system=repair_system, user=repair_user)
            commands, errors = self._parse_and_validate(repaired)

        if errors:
            raise LLMValidationError(f"invalid commands after LLM: {errors}")
        if not commands:
            raise LLMValidationError("Agent 1 returned an empty command list")

        # Rule-based classification is authoritative; override whatever the LLM claimed.
        for command in commands:
            command["risk"] = classify_risk(command["action"], command["parameters"])

        return commands

    @staticmethod
    def _parse_and_validate(payload: object) -> tuple[list[dict], list[str]]:
        try:
            commands = parser.parse_commands(payload)
        except parser.ParseError as exc:
            return [], [str(exc)]
        errors = []
        for index, command in enumerate(commands):
            valid, message = validate_command(command)
            if not valid:
                errors.append(f"command[{index}]: {message}")
        return commands, errors


class StubAgent1:
    """Development stand-in used before Agent 1 wiring (dry-run pipeline)."""

    def __call__(self, request: str, session_context: dict) -> list[dict]:
        return [
            {
                "action": "TAKE_SCREENSHOT",
                "parameters": {},
                "risk": "low",
            }
        ]