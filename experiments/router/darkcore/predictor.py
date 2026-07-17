"""Layer 2 — the predictor, in CLASS-PRIOR mode (P1-constrained).

Exp 1 / P1: embeddings see *class*, not *difficulty*. So at low n this layer
contributes CLASS ONLY — which bge-small does nearly perfectly (12/12 LOO on
the battery, ~8 ms/query) — and abstains from tier prediction until the
exemplar corpus grows (Phase 0). Fixes the P-class lexicon miss (E3).

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
        self._tok = None
        self._mdl = None

    def warm(self):
        """Load the embedder eagerly (router init, not first query)."""
        if self._mdl is None:
            import torch
            from transformers import AutoModel, AutoTokenizer
            torch.set_num_threads(1)  # 33M params: thread fan-out costs more
            # than it buys, and 1 thread contends least with resident mlx
            # models (measured: 6ms solo either way; bench showed 24ms under
            # co-residency at default threads)
            self._tok = AutoTokenizer.from_pretrained(self.embedder_id)
            self._mdl = AutoModel.from_pretrained(self.embedder_id).eval()
            self.embed("warmup")  # first-call graph/cache built at init
        return self

    def embed(self, text):
        import torch
        self.warm()
        with torch.no_grad():
            enc = self._tok([text], padding=True, truncation=True,
                            max_length=512, return_tensors="pt")
            e = self._mdl(**enc).last_hidden_state[:, 0]
            return torch.nn.functional.normalize(e, dim=1).numpy()[0]

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
