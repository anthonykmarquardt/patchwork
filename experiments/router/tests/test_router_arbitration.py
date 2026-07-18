"""Layer arbitration (journal Episode 6, step 1) + dark-operability, pinned.

Rules win when they fire > embedder class-prior > abstain to default.
The predictor may never break the data path. Cascade is stubbed."""
import pytest

from darkcore import router as router_module
from darkcore import surface


def make_config(**param_over):
    import copy
    cfg = copy.deepcopy(surface.DEFAULTS)
    cfg["config_version"] = 7
    cfg["params"].update(param_over)
    return cfg


class FakePrior:
    def __init__(self, verdict=None, exc=None, forbid=False):
        self.verdict = verdict
        self.exc = exc
        self.forbid = forbid
        self.index_version = 1
        self.embedder_id = "test-embedder"
        self.ids = ["x"]

    def classify(self, text):
        assert not self.forbid, "predictor consulted although a rule fired"
        if self.exc:
            raise self.exc
        return self.verdict


@pytest.fixture()
def harness(monkeypatch):
    """Router wired to a crafted config + stubbed cascade. Returns a factory:
    route(query, config=..., prior=...) -> (result, captured cascade kwargs)."""
    captured = {}

    def fake_cascade_run(pool, query, qhash, route_id, klass, start_tier,
                        params, on_event=None, messages=None):
        captured.update(klass=klass, start=start_tier, messages=messages)
        return {"answer": "a", "final_tier": start_tier, "escalations": 0,
                "flagged": False, "attempts": [{"tier": start_tier, "outcome": "pass"}],
                "total_ms": 1.0}

    monkeypatch.setattr(router_module.cascade, "run", fake_cascade_run)

    def build(config, prior=None):
        monkeypatch.setattr(surface, "load_config", lambda: (config, []))
        monkeypatch.setattr(surface, "config_mtime", lambda: 1)
        r = router_module.Router()
        r._prior = prior
        return r, captured

    return build


def test_rule_beats_embedder(harness):
    r, cap = harness(make_config(), prior=FakePrior(forbid=True))
    out = r.route("please review this: ```py\nx=1\n```")
    assert cap["klass"] == "agentic" and out["trace"]["prefilter"]["matched_rule"]


def test_embedder_owns_the_rest(harness):
    prior = FakePrior({"class": "emotional", "confidence": 0.8,
                       "neighbors": ["b1"], "abstained": False})
    r, cap = harness(make_config(), prior=prior)
    r.route("something with no rule signal at all")
    assert cap["klass"] == "emotional"
    assert cap["start"] == "T1"                  # emotional floor enforced


def test_abstention_falls_to_default(harness):
    prior = FakePrior({"class": "default", "confidence": 0.3,
                       "neighbors": [], "abstained": True})
    r, cap = harness(make_config(), prior=prior)
    r.route("ambiguous mumbling with no signal")
    assert cap["klass"] == "default"


def test_skip_start_bumps_unclassifiable(harness):
    cfg = make_config()
    cfg["params"]["cascade_policy"] = {**cfg["params"]["cascade_policy"],
                                       "skip_start": True}
    r, cap = harness(cfg, prior=None)
    r.route("ambiguous mumbling with no signal")
    assert cap["klass"] == "default" and cap["start"] == "T1"   # T0 skipped


def test_predictor_crash_never_breaks_routing(harness, log_events):
    r, cap = harness(make_config(), prior=FakePrior(exc=RuntimeError("torch gone")))
    out = r.route("something with no rule signal at all")
    assert cap["klass"] == "default" and out["answer"] == "a"
    assert any(e["event"] == "predictor_error" for e in log_events())


def test_floor_beats_start(harness):
    cfg = make_config(class_start_map={"emotional": "T1", "default": "T0"},
                      class_floor={"emotional": "T1", "default": "T1"})
    r, cap = harness(cfg, prior=None)
    r.route("no signal here either")
    assert cap["start"] == "T1"


def test_context_counts_in_trace_and_messages_passthrough(harness):
    r, cap = harness(make_config(), prior=None)
    convo = [{"role": "system", "content": "s"},
             {"role": "user", "content": "how many stars are there?"}]
    out = r.route("how many stars are there?", messages=convo)
    assert cap["messages"] == convo
    assert out["trace"]["config_version"] == 7
