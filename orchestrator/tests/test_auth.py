from orchestrator.auth import SenderAuth


class TestSenderAuth:
    def test_allowed_user_is_authorized(self):
        auth = SenderAuth({111, 222})
        assert auth.is_authorized(111) is True
        assert auth.is_authorized(222) is True

    def test_unknown_user_is_rejected(self):
        auth = SenderAuth({111})
        assert auth.is_authorized(999) is False

    def test_empty_allowlist_rejects_everyone(self):
        auth = SenderAuth(set())
        assert auth.is_authorized(111) is False

    def test_allowed_list_exposed(self):
        auth = SenderAuth({222, 111})
        assert auth.allowed == [111, 222]