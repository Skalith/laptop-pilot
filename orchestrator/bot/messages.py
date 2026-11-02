from __future__ import annotations

from html import escape as _html_escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PARSE_MODE_HTML = "HTML"


def b(text: str) -> str:
    return f"<b>{_html_escape(text)}</b>"


def code(text: str) -> str:
    return f"<code>{_html_escape(text)}</code>"


def i(text: str) -> str:
    return f"<i>{_html_escape(text)}</i>"


def risk_label(risk: str | None) -> str:
    return (risk or "unknown").upper()


def approval_one_text(request_id: str, commands: list[dict], risk: str | None) -> str:
    lines = [b("Approval #1 required"), ""]
    lines.append(f"Request {code(request_id)} · risk: {b(risk_label(risk))}")
    for index, cmd in enumerate(commands, 1):
        params = cmd.get("parameters") or {}
        detail = ", ".join(f"{k}={v}" for k, v in params.items()) or i("no parameters")
        lines.append(f"{index}. {b(cmd.get('action', '?'))} — {detail}")
    return "\n".join(lines)


def approval_two_text(request_id: str, plan: list, risk: str | None) -> str:
    lines = [b("Approval #2 required"), ""]
    lines.append(f"Request {code(request_id)} · risk: {b(risk_label(risk))}")
    lines.append(b("Execution plan:"))
    for step in plan:
        lines.append(f"• {_html_escape(str(step))}")
    return "\n".join(lines)


def result_text(result: dict) -> str:
    lines = [b("Execution result")]
    for item in result.get("results", []):
        name = item.get("name") or item.get("action") or "?"
        status = item.get("status")
        output = (item.get("output") or item.get("error") or "OK")
        output = str(output)[:1000]
        lines.append(f"• {code(str(name))} → {b(status)}: {output}")
    if result.get("cwd"):
        lines.append(f"CWD: {code(str(result['cwd']))}")
    if result.get("error"):
        lines.append(f"Error: {result['error']}")
    return "\n".join(lines)


def error_text(error: str) -> str:
    return f"⚠️ {_html_escape(error)}"


def approval_keyboard(*buttons: tuple[str, str]) -> InlineKeyboardMarkup:
    """Build a keyboard; each entry is (label, callback_data)."""
    rows = [[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]]
    return InlineKeyboardMarkup(rows)


def approval_one_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return approval_keyboard(("APPROVE", f"approve1:{request_id}"), ("DISAPPROVE", f"disapprove1:{request_id}"))


def approval_two_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return approval_keyboard(("EXECUTE", f"execute2:{request_id}"), ("CANCEL", f"cancel2:{request_id}"))


def parse_callback_data(data: str) -> tuple[str, int, str]:
    """'approve1:<request_id>' -> ('approve', 1, request_id)."""
    label, _, request_id = data.partition(":")
    keys = {"approve1": ("approve", 1), "disapprove1": ("disapprove", 1), "execute2": ("execute", 2), "cancel2": ("cancel", 2)}
    if label not in keys or not request_id:
        raise ValueError(f"unknown callback data: {data}")
    decision, phase = keys[label]
    return decision, phase, request_id