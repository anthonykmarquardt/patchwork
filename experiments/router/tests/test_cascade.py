"""Cascade spine: verify-and-escalate with a scripted pool. No models."""
import pytest

from darkcore import cascade, verifiers
from tests.conftest import FakePool, minimal_params, unavailable


@pytest.fixture()
def registry(monkeypatch):
    """Deterministic test verifiers registered under controllable names."""
    def make(verdicts):
        it = iter(verdicts)
        def fn(query, answer, pool, tier, ctx):
            passed = next(it)
            return passed, {"rung": 4, "check": "scripted", "verify_ms": 0.1}
        return fn

    def register(name, verdicts):
        monkeypatch.setitem(verifiers.REGISTRY, name, make(verdicts))
    return register


def run(pool, params, klass="default", start="T0", **kw):
    return cascade.run(pool, "q", "qhash", "rid", klass, start, params, **kw)


def test_pass_at_start_no_escalation(registry):
    registry("_test", [True])
    out = run(FakePool({"T0": {"answer": "ok"}}), minimal_params())
    assert out["final_tier"] == "T0" and out["escalations"] == 0
    assert out["answer"] == "ok" and not out["flagged"]
    assert [a["outcome"] for a in out["attempts"]] == ["pass"]


def test_fail_escalates_then_passes(registry):
    registry("_test", [False, True])
    out = run(FakePool({"T0": {}, "T1": {"answer": "better"}}), minimal_params())
    assert out["final_tier"] == "T1" and out["escalations"] == 1
    assert out["answer"] == "better"
    assert [a["outcome"] for a in out["attempts"]] == ["fail", "pass"]


def test_infra_failover_is_not_an_escalation(registry):
    """TierUnavailable != verifier failure: the unavailable attempt is
    excluded from the escalation count."""
    registry("_test", [True])
    out = run(FakePool({"T0": unavailable(), "T1": {}}), minimal_params())
    assert out["final_tier"] == "T1"
    assert out["escalations"] == 0                       # the pinned arithmetic
    assert [a["outcome"] for a in out["attempts"]] == ["unavailable", "pass"]


def test_terminal_failure_flags_and_emits(registry):
    registry("_test", [False, False, False])
    out = run(FakePool({"T0": {}, "T1": {}, "T2": {"answer": "last"}}),
              minimal_params())
    assert out["flagged"] and out["final_tier"] == "T2"
    assert out["answer"] == "last"                       # emit_flagged, never silent


def test_max_tiers_budget_stops_climb(registry):
    registry("_test", [False, False])
    p = minimal_params()
    p["cascade_policy"] = {**p["cascade_policy"], "max_tiers_per_query": 1}
    out = run(FakePool({"T0": {}, "T1": {}}), p)
    assert out["flagged"] and len(out["attempts"]) == 1


def test_wall_clock_budget_stops_climb(registry):
    """Budget is checked before each attempt: a slow first attempt burns the
    budget, so the escalation never runs."""
    registry("_test", [False, False])
    p = minimal_params()
    p["cascade_policy"] = {**p["cascade_policy"], "per_query_ms_budget": 5}
    out = run(FakePool({"T0": {"sleep_s": 0.02}, "T1": {}}), p)
    assert out["flagged"] and len(out["attempts"]) == 1


def test_rung5_fixed_policy_never_verifies(registry):
    registry("_test", [False])  # would fail if consulted
    p = minimal_params(verifier_config={
        "emotional": {"rung": 5, "verifier": None, "thresholds": {}},
        "default": {"rung": 4, "verifier": "_test", "thresholds": {}},
    })
    out = run(FakePool({"T1": {}}), p, klass="emotional", start="T1")
    assert out["final_tier"] == "T1" and not out["flagged"]
    assert out["attempts"][0]["rung"] == 5


def test_escalation_override_pins_start(registry):
    registry("_test", [True])
    p = minimal_params(escalation_overrides={"default": "T2"})
    pool = FakePool({"T2": {}})
    out = run(pool, p, start="T0")
    assert out["final_tier"] == "T2" and pool.calls[0][0] == "T2"


def test_messages_passthrough_to_generation(registry):
    """Seam 1: the full conversation reaches the pool, not just the query."""
    registry("_test", [True])
    convo = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    pool = FakePool({"T0": {}})
    run(pool, minimal_params(), messages=convo)
    assert pool.calls == [("T0", convo)]
