from orchestrator.session import SessionRegistry, SessionState


class TestSessionState:
    def test_default_cwd_is_home(self):
        s = SessionState(user_id=1)
        assert s.cwd == "~/"

    def test_update_cwd_ignores_empty(self):
        s = SessionState(user_id=1)
        s.update_cwd(None)
        s.update_cwd("")
        assert s.cwd == "~/"
        s.update_cwd("/home/u/projects")
        assert s.cwd == "/home/u/projects"

    def test_context_exposes_state(self):
        s = SessionState(user_id=1, cwd="/x")
        s.update_cwd("/y")
        ctx = s.context()
        assert ctx["cwd"] == "/y"
        assert ctx["auto_proceed_low_risk"] is False

    def test_history_is_capped(self):
        s = SessionState(user_id=1)
        for i in range(60):
            s.add_exchange(f"req{i}", {"ok": i})
        assert len(s.history) == 50
        assert s.history[0]["request"] == "req10"


class TestSessionRegistry:
    def test_get_or_create_returns_same_session(self):
        reg = SessionRegistry()
        a = reg.get_or_create(1)
        b = reg.get_or_create(1)
        assert a is b

    def test_get_missing_returns_none(self):
        reg = SessionRegistry()
        assert reg.get(42) is None

    def test_all_lists_created_sessions(self):
        reg = SessionRegistry()
        reg.get_or_create(1)
        reg.get_or_create(2)
        assert {s.user_id for s in reg.all()} == {1, 2}