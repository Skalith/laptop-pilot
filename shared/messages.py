from __future__ import annotations


class EventType:
    """Audit log event types."""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    COMMAND_GENERATED = "COMMAND_GENERATED"
    APPROVAL_1_SENT = "APPROVAL_1_SENT"
    APPROVAL_1_RESULT = "APPROVAL_1_RESULT"
    COMMAND_DISPATCHED = "COMMAND_DISPATCHED"
    APPROVAL_2_SENT = "APPROVAL_2_SENT"
    APPROVAL_2_RESULT = "APPROVAL_2_RESULT"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    ERROR = "ERROR"


class MessageType:
    """Envelope types exchanged over the relay / between components."""

    DISPATCH_COMMAND = "DISPATCH_COMMAND"
    APPROVAL_2_PLAN = "APPROVAL_2_PLAN"
    EXECUTE_SIGNAL = "EXECUTE_SIGNAL"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    ERROR = "ERROR"


def envelope(message_type: str, **fields) -> dict:
    """Build a standard relay envelope: {"type": ..., **fields}."""
    return {"type": message_type, **fields}