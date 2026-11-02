from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class Action(str, Enum):
    CHANGE_DIRECTORY = "CHANGE_DIRECTORY"
    OPEN_APPLICATION = "OPEN_APPLICATION"
    RUN_COMMAND = "RUN_COMMAND"
    FILE_OPERATION = "FILE_OPERATION"
    CLOSE_APPLICATION = "CLOSE_APPLICATION"
    TAKE_SCREENSHOT = "TAKE_SCREENSHOT"


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Command(BaseModel):
    """A single validated, risk-classified command."""

    action: Action
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: Risk

    @field_validator("parameters")
    @classmethod
    def parameters_must_be_dict(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("parameters must be an object/dict")
        return value


def validate_command(command: dict | Command) -> tuple[bool, str | None]:
    """Validate a command object against the action schema.

    Returns (is_valid, error_message). error_message is None when valid.
    """
    try:
        if isinstance(command, Command):
            Command.model_validate(command)
        else:
            Command.model_validate(command)
        return True, None
    except (ValidationError, TypeError, ValueError) as exc:
        return False, str(exc)