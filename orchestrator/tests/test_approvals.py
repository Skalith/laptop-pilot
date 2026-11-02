from orchestrator.approvals import APPROVAL_KIND_1, APPROVAL_KIND_2, ApprovalStore


class FakeClock:
    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestApprovalStore:
    def test_add_and_get(self):
        store = ApprovalStore(ttl_seconds=180)
        store.add("r1", APPROVAL_KIND_1, {"commands": []})
        approval = store.get("r1")
        assert approval.request_id == "r1"
        assert approval.kind == APPROVAL_KIND_1
        assert approval.expires_at == approval.created_at + 180

    def test_resolve_removes(self):
        store = ApprovalStore(ttl_seconds=180)
        store.add("r1", APPROVAL_KIND_2, {})
        assert store.resolve("r1") is not None
        assert store.resolve("r1") is None
        assert store.pending_count() == 0

    def test_not_expired_within_ttl(self):
        clock = FakeClock()
        store = ApprovalStore(ttl_seconds=180, clock=clock)
        store.add("r1", APPROVAL_KIND_1, {})
        clock.advance(179)
        assert store.expire_due() == []
        assert store.pending_count() == 1

    def test_expires_after_ttl_and_is_removed(self):
        clock = FakeClock()
        store = ApprovalStore(ttl_seconds=180, clock=clock)
        store.add("r1", APPROVAL_KIND_1, {})
        clock.advance(180)
        expired = store.expire_due()
        assert [a.request_id for a in expired] == ["r1"]
        assert store.pending_count() == 0

    def test_multiple_expirations_returned(self):
        clock = FakeClock()
        store = ApprovalStore(ttl_seconds=180, clock=clock)
        store.add("r1", APPROVAL_KIND_1, {})
        store.add("r2", APPROVAL_KIND_2, {})
        clock.advance(181)
        expired = store.expire_due()
        assert {a.request_id for a in expired} == {"r1", "r2"}
        assert store.pending_ids() == []