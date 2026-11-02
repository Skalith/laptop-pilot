import pytest

from orchestrator.config import Settings


class TestSettingsFromEnv:
    def test_parses_authorized_ids_list(self):
        settings = Settings.from_env(
            {"AUTHORIZED_USER_ID": "111, 222, 333", "TELEGRAM_BOT_TOKEN": "tok"}
        )
        assert settings.authorized_user_ids == {111, 222, 333}

    def test_non_numeric_ids_are_skipped(self):
        settings = Settings.from_env({"AUTHORIZED_USER_ID": "111, abc, 222"})
        assert settings.authorized_user_ids == {111, 222}

    def test_defaults_applied(self):
        settings = Settings.from_env({})
        assert settings.approval_ttl_seconds == 180
        assert settings.auto_proceed_low_risk is False
        assert settings.log_path == "./logs/audit.log"
        assert settings.relay_url == "ws://localhost:8765"

    def test_bool_and_int_parsing(self):
        settings = Settings.from_env(
            {"APPROVAL_TTL_SECONDS": "90", "AUTO_PROCEED_LOW_RISK": "true"}
        )
        assert settings.approval_ttl_seconds == 90
        assert settings.auto_proceed_low_risk is True

    def test_llm_keys_fowarded_to_factory(self):
        settings = Settings.from_env(
            {"LLM_PROVIDER_ORDER": "gemini", "GEMINI_API_KEY": "abc"}
        )
        assert settings.llm["LLM_PROVIDER_ORDER"] == "gemini"
        assert settings.llm["GEMINI_API_KEY"] == "abc"


class TestSettingsValidate:
    def test_ok_when_required_present(self):
        settings = Settings(authorized_user_ids={1}, relay_url="ws://x", relay_secret="s")
        assert settings.validate() == []

    def test_missing_values_reported(self):
        settings = Settings()
        errors = settings.validate()
        assert "AUTHORIZED_USER_ID" in errors
        assert "RELAY_SECRET" in errors