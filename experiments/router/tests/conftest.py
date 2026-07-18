"""Shared fixtures. Model-free by construction: every mlx/torch import in
darkcore is lazy, and these stubs keep tests on the pure-logic paths.

Telemetry is redirected BEFORE any darkcore import (LOG_DIR is bound at
import time) so tests never write to the real logs/router/."""
import json
import os
import tempfile
import time

_TEST_LOG_DIR = tempfile.mkdtemp(prefix="darkcore-test-logs-")
os.environ["DARKCORE_LOG_DIR"] = _TEST_LOG_DIR

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from darkcore import surface, telemetry  # noqa: E402
from darkcore.models import TierUnavailable  # noqa: E402


@pytest.fixture()
def isolated_surface(tmp_path, monkeypatch):
    """Point the control surface at throwaway files — set_config tests must
    never touch the real config.json/journal."""
    cfg = tmp_path / "config.json"
    journal = tmp_path / "config.journal.jsonl"
    monkeypatch.setattr(surface, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(surface, "JOURNAL_PATH", str(journal))
    return {"config": cfg, "journal": journal}


@pytest.fixture()
def log_events():
    """Events emitted during the test, parsed from the isolated log sink."""
    def _read():
        events = []
        for name in sorted(os.listdir(_TEST_LOG_DIR)):
            with open(os.path.join(_TEST_LOG_DIR, name)) as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events

    marker = len(_read())
    yield lambda: _read()[marker:]


class FakePool:
    """Scripted stand-in for ModelPool. script: tier -> result-overrides dict,
    or a TierUnavailable instance to simulate infra failure."""

    def __init__(self, script, order=("T0", "T1", "T2")):
        self.order = list(order)
        self.script = script
        self.calls = []          # (tier, messages) per generate
        self.exclusive_used = False
        self._live = {}

    def generate(self, tier, query, max_tokens=None, messages=None):
        self.calls.append((tier, messages))
        r = self.script[tier]
        if isinstance(r, Exception):
            raise r
        if r.get("sleep_s"):
            time.sleep(r["sleep_s"])
        return {
            "answer": r.get("answer", f"{tier}-answer"),
            "tier": tier, "load_ms": 0.0, "ttft_ms": 1.0,
            "gen_ms": r.get("gen_ms", 5.0), "tokens": r.get("tokens", 3),
            "prompt_tokens": r.get("prompt_tokens", 2), "tps": 1.0,
        }

    def next_tier(self, tier):
        i = self.order.index(tier)
        return self.order[i + 1] if i + 1 < len(self.order) else None


def unavailable():
    return TierUnavailable("down")


def minimal_params(**over):
    """Smallest params dict cascade.run needs, with test verifier names the
    tests register into verifiers.REGISTRY via monkeypatch."""
    p = {
        "cascade_policy": {
            "max_tiers_per_query": 3,
            "per_query_ms_budget": 300000,
            "retry_policy": "escalate",
            "skip_start": False,
            "terminal_failure": "emit_flagged",
        },
        "verifier_config": {
            "default": {"rung": 4, "verifier": "_test", "thresholds": {}},
        },
        "escalation_overrides": {},
        "_expected": [],
    }
    p.update(over)
    return p


@pytest.fixture()
def store(tmp_path):
    """Synthetic exemplar snapshot: 4 exemplars, 2 classes.

    Geometry chosen for three probes (SELF_SIM = 0.995, K = 3):
      [0.98, 0.199, 0]  -> a1/a2 similar-but-not-identical: majority vote
      [1, 0, 0]         -> a1 (sim 1.0) and a2 (sim ~0.9999) both excluded
      [0, 0, 1]         -> everything near-orthogonal: abstention"""
    d = tmp_path / "v1"
    d.mkdir()
    E = np.array([[1.0, 0.0, 0.0],
                  [0.9999, 0.0141, 0.0],
                  [0.0, 1.0, 0.0],
                  [0.0, 0.96, 0.28]], dtype=np.float32)
    np.save(d / "embeddings.npy", E)
    (d / "meta.json").write_text(json.dumps({
        "version": 1, "embedder": "test-embedder", "n": 4,
        "ids": ["a1", "a2", "b1", "b2"],
        "classes": ["agentic", "agentic", "emotional", "emotional"],
    }))
    return str(d)
