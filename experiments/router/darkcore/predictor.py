"""Layer 2 — the predictor, in CLASS-PRIOR mode (P1-constrained).

Exp 1 / P1: embeddings see *class*, not *difficulty*. So at low n this layer
contributes CLASS ONLY — which bge-small does nearly perfectly (12/12 LOO on
the battery) — and abstains from tier prediction until the exemplar corpus
grows (Phase 0). Fixes the P-class lexicon miss (E3).

The embedder is the mlx port (embedder_mlx.py) as of 2026-07-18 — same
weights, parity-gated against the frozen torch reference
(fixtures/embedder-parity/). No torch in the query path.

Reads immutable snapshot stores per control-surface.md §5. Snapshots hold
embeddings + ids/classes/hashes — never raw text (PII rule).
"""
import json
import os

import numpy as np

CONF_THRESHOLD = 0.50  # correct LOO preds measured >= 0.57; below -> "default"
SELF_SIM = 0.995       # near-identical exemplar excluded (bench honesty; a
                       # production exact-repeat falls back to its neighbors)
K = 3


class ClassPrior:
    def __init__(self, store_uri):
        meta = json.load(open(os.path.join(store_uri, "meta.json")))
        self.embedder_id = meta["embedder"]
        self.index_version = meta["version"]
        self.ids = meta["ids"]
        self.classes = meta["classes"]
        self.E = np.load(os.path.join(store_uri, "embeddings.npy"))
        self._emb = None

    def warm(self):
        """Load the embedder eagerly (router init, not first query)."""
        if self._emb is None:
            from .embedder_mlx import MlxEmbedder
            self._emb = MlxEmbedder(self.embedder_id).warm()
        return self

    def embed(self, text):
        self.warm()
        return self._emb.embed(text)

    def classify(self, text):
        """kNN class vote. Returns {class, confidence, neighbors} —
        class 'default' when confidence is below threshold (abstain)."""
        q = self.embed(text)
        sims = self.E @ q
        order = np.argsort(-sims)
        picked = [i for i in order if sims[i] < SELF_SIM][:K]
        votes = {}
        for i in picked:
            votes.setdefault(self.classes[i], []).append(float(sims[i]))
        cls, ss = max(votes.items(), key=lambda kv: (len(kv[1]), sum(kv[1])))
        conf = float(np.mean(ss))
        result_class = cls if conf >= CONF_THRESHOLD else "default"
        return {
            "class": result_class,
            "confidence": round(conf, 3),
            "neighbors": [self.ids[i] for i in picked],
            "abstained": result_class == "default",
        }
