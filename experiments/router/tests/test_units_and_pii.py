"""Pure-function pins (extraction, prefilter, predictor) + the PII tripwire."""
import numpy as np
import pytest

from darkcore import prefilter, surface, telemetry
from darkcore.models import extract_answer
from darkcore.predictor import ClassPrior, CONF_THRESHOLD


# -------------------------------------------------- answer extraction (27B leak)
@pytest.mark.parametrize("raw,want", [
    ("<think>internal</think>Plain answer.", "Plain answer."),
    # the Bonsai-27B leak: CoT narrated as prose, no opening tag
    ("Here's a thinking process:\n1. hm\n</think>\n\nThe answer is 42.",
     "The answer is 42."),
    ("No think tags at all.", "No think tags at all."),
    # everything stripped -> fall back to raw, never emit empty
    ("Only reasoning then</think>", "Only reasoning then</think>"),
])
def test_extract_answer(raw, want):
    assert extract_answer(raw) == want


# ------------------------------------------------------------------ prefilter
RULES = surface.DEFAULTS["params"]["prefilter_rules"]


@pytest.mark.parametrize("query,klass,rule", [
    ("review this ```python\nx=1\n``` please", "agentic", "code-fence"),
    ("use tools: search/browser/calculator to plan", "agentic", "tool-list"),
    ("I feel completely stuck and it hurts", "emotional", "affective"),
    ("how many primes are below 100", "reasoning", "reasoning-shape"),
    ("tell me about the weather patterns", "default", None),
])
def test_prefilter_shipped_rules(query, klass, rule):
    verdict = prefilter.run(query, RULES)
    assert verdict["class"] == klass
    assert verdict["matched_rule"] == rule


def test_prefilter_first_match_wins():
    # affective cue AND code fence: rule order in DEFAULTS puts code-fence first
    q = "I feel bad about this ```code```"
    assert prefilter.run(q, RULES)["matched_rule"] == "code-fence"


def test_tool_names_extraction():
    assert prefilter.tool_names("tools: search/browser/calc") == \
        ["search", "browser", "calc"]
    assert prefilter.tool_names("no roster here") == []


# ------------------------------------------------------------------ predictor
def make_prior(store, vec):
    p = ClassPrior(store)
    p.embed = lambda text: np.asarray(vec, dtype=np.float32)  # no torch
    return p


def test_knn_majority_vote(store):
    v = make_prior(store, [0.98, 0.199, 0]).classify("q")
    assert v["class"] == "agentic" and not v["abstained"]
    assert v["confidence"] >= CONF_THRESHOLD


def test_low_confidence_abstains_to_default(store):
    # near-orthogonal to every exemplar -> similarities ~0 -> abstain
    v = make_prior(store, [0, 0, 1]).classify("q")
    assert v["class"] == "default" and v["abstained"]


def test_self_similar_exemplar_excluded(store):
    """An exact-repeat neighbor (cos >= SELF_SIM) must not vote for itself."""
    v = make_prior(store, [1, 0, 0]).classify("q")
    # a1/a2 are identical unit vectors: both are ~1.0 similar and excluded,
    # so the vote falls to the remaining neighbors (emotional at sim 0)
    assert set(v["neighbors"]).isdisjoint({"a1", "a2"})


# ---------------------------------------------------------------- PII tripwire
def test_sink_refuses_content_keys():
    with pytest.raises(AssertionError, match="PII rule"):
        telemetry.emit("bad_event", query="raw user text")


def test_route_telemetry_carries_no_content(monkeypatch, log_events):
    """End-to-end through route() with stubbed cascade: the sentinel query
    string must never appear in any emitted event — hash + features only."""
    import copy
    from darkcore import router as router_module

    def fake_run(pool, query, qhash, route_id, klass, start_tier, params,
                 on_event=None, messages=None):
        return {"answer": "SENTINEL-ANSWER", "final_tier": "T0",
                "escalations": 0, "flagged": False,
                "attempts": [{"tier": "T0", "outcome": "pass"}], "total_ms": 1.0}

    monkeypatch.setattr(router_module.cascade, "run", fake_run)
    monkeypatch.setattr(surface, "load_config",
                        lambda: (copy.deepcopy(surface.DEFAULTS), []))
    monkeypatch.setattr(surface, "config_mtime", lambda: 1)

    sentinel = "XYZZY-the-operator-wrote-something-private-XYZZY"
    router_module.Router().route(sentinel)

    events = log_events()
    assert events, "route emitted no telemetry"
    blob = "\n".join(str(e) for e in events)
    assert "XYZZY" not in blob
    assert any(e.get("qhash") == telemetry.query_hash(sentinel)
               for e in events)
