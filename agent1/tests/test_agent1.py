from __future__ import annotations

import json

import pytest

from agent1.agent import Agent1, LLMValidationError
from agent1.parser import ParseError, parse_commands
from shared.action_schema import validate_command


class FakeLLM:
    """Returns canned payloads; records prompts."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, *, system, user, max_tokens=1024):
        self.calls.append((system, user))
        if not self.payloads:
            raise RuntimeError("no payload queued")
        return self.payloads.pop(0)


BASE_CONTEXT = {"cwd": "~/", "conversation_history": [], "last_known_laptop_state": None}

VALID_PAYLOAD = {
    "commands": [
        {"action": "CHANGE_DIRECTORY", "parameters": {"path": "~/projects/backend"}, "risk": "low"},
        {"action": "OPEN_APPLICATION", "parameters": {"application": "vscode", "target": "~/projects/backend"}, "risk": "low"},
    ]
}


class TestParseCommands:
    def test_accepts_commands_key(self):
        assert parse_commands(VALID_PAYLOAD) == VALID_PAYLOAD["commands"]

    def test_accepts_bare_list(self):
        cmds = [{"action": "TAKE_SCREENSHOT", "parameters": {}, "risk": "low"}]
        assert parse_commands(cmds) == cmds

    def test_accepts_json_string(self):
        data = json.dumps(VALID_PAYLOAD)
        assert parse_commands(data) == VALID_PAYLOAD["commands"]

    def test_rejects_wrapped_in_code_fences(self):
        fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
        assert parse_commands(fenced) == VALID_PAYLOAD["commands"]

    def test_missing_commands_key_raises(self):
        with pytest.raises(ParseError):
            parse_commands({"foo": 1})

    def test_non_dict_entries_raise(self):
        with pytest.raises(ParseError):
            parse_commands({"commands": ["nope"]})


class TestAgent1:
    @staticmethod
    def make_agent(llm_payloads):
        return Agent1(FakeLLM(llm_payloads))

    def test_returns_non_empty_schema_valid_commands(self):
        agent = self.make_agent([VALID_PAYLOAD])
        commands = agent.generate_commands("Open VS Code in backend", BASE_CONTEXT)
        assert len(commands) == 2
        for cmd in commands:
            assert validate_command(cmd) == (True, None)

    def test_risk_is_reclassified_by_rule_based_classifier(self):
        # LLM claims low, but classifier must say high for arbitrary RUN_COMMAND
        malicious = {"commands": [{"action": "RUN_COMMAND", "parameters": {"command": "rm -rf /tmp/x"}, "risk": "low"}]}
        agent = self.make_agent([malicious])
        commands = agent.generate_commands("delete temp", BASE_CONTEXT)
        assert commands[0]["risk"] == "high"

    def test_repairs_invalid_first_answer(self):
        bad = {"commands": [{"action": "NOT_A_REAL_ACTION", "parameters": {}, "risk": "low"}]}
        agent = self.make_agent([bad, VALID_PAYLOAD])
        commands = agent.generate_commands("open vscode", BASE_CONTEXT)
        assert all(validate_command(c) == (True, None) for c in commands)
        assert len(agent.llm.calls) == 2

    def test_repair_exhausted_raises_clear_error(self):
        bad = {"commands": [{"action": "NOPE", "parameters": {}, "risk": "low"}]}
        agent = self.make_agent([bad, bad])
        with pytest.raises(LLMValidationError, match="invalid commands"):
            agent.generate_commands("do it", BASE_CONTEXT)
        assert len(agent.llm.calls) == 2

    def test_unparseable_payload_raises(self):
        bad = {"nope": True}
        agent = self.make_agent([bad, bad])
        with pytest.raises(LLMValidationError):
            agent.generate_commands("do it", BASE_CONTEXT)

    def test_empty_command_list_raises(self):
        agent = self.make_agent([{"commands": []}])
        with pytest.raises(LLMValidationError, match="empty command list"):
            agent.generate_commands("do nothing", BASE_CONTEXT)

    def test_llm_raise_propagates(self):
        llm = FakeLLM([])
        agent = Agent1(llm)
        with pytest.raises(RuntimeError):
            agent.generate_commands("do it", BASE_CONTEXT)

    def test_session_context_forwarded_to_llm(self):
        ctx = {"cwd": "~/projects", "conversation_history": [{"request": "hi"}], "last_known_laptop_state": None}
        agent = self.make_agent([VALID_PAYLOAD])
        agent.generate_commands("go to backend", ctx)
        system, user = agent.llm.calls[0]
        assert "chANGE" not in user
        assert "~/projects" in user
        assert "CHANGE_DIRECTORY" in system