#!/usr/bin/env python3
"""Seed exemplar snapshot v1 and publish it through the control surface.

Plays the TUNER's role (single writer, control-surface.md §5): builds an
immutable snapshot darkcore/exemplars/v<N>/ (embeddings + ids/classes/hashes,
NEVER raw text), then publishes it with one set_config patch:
exemplar_store_ref + predictor_enabled (+ cascade_policy.skip_start for the
v0.2 bench — journal Episode 6, step 2).

  HF_HUB_OFFLINE=1 $MLXPY experiments/router/seed_exemplars.py

Sources: battery.jsonl (12) + exemplar-seeds.jsonl (9 authored) = n=21.
"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np  # noqa: E402

from darkcore import surface  # noqa: E402

VERSION = 1
STORE = os.path.join(HERE, "darkcore", "exemplars", f"v{VERSION}")


def main():
    rows = []
    for fname in ("battery.jsonl", "exemplar-seeds.jsonl"):
        for line in open(os.path.join(HERE, fname)):
            if line.strip():
                r = json.loads(line)
                rows.append((r["id"], r["class"], r["query"]))

    from transformers import AutoModel, AutoTokenizer
    import torch
    tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    mdl = AutoModel.from_pretrained("BAAI/bge-small-en-v1.5").eval()
    with torch.no_grad():
        enc = tok([q for _, _, q in rows], padding=True, truncation=True,
                  max_length=512, return_tensors="pt")
        E = mdl(**enc).last_hidden_state[:, 0]
        E = torch.nn.functional.normalize(E, dim=1).numpy().astype(np.float32)

    os.makedirs(STORE, exist_ok=True)
    np.save(os.path.join(STORE, "embeddings.npy"), E)
    meta = {
        "version": VERSION,
        "embedder": "BAAI/bge-small-en-v1.5",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": len(rows),
        "ids": [i for i, _, _ in rows],
        "classes": [c for _, c, _ in rows],
        "query_hashes": [hashlib.sha256(q.encode()).hexdigest()[:12] for _, _, q in rows],
        "content_hash": hashlib.sha256(E.tobytes()).hexdigest()[:16],
        "note": "seed corpus: battery + authored exemplars; no raw text in snapshot (PII rule)",
    }
    with open(os.path.join(STORE, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"snapshot v{VERSION}: n={meta['n']} -> {STORE}")

    cfg = surface.get_config()
    res = surface.set_config(
        {
            "exemplar_store_ref": {"uri": STORE, "index_version": VERSION},
            "predictor_enabled": True,
            "cascade_policy": {"skip_start": True},
        },
        base_version=cfg["config_version"],
        actor="operator",
        note="seed exemplar snapshot v1 (class-prior); enable predictor + skip_start for bench v0.2",
    )
    print("set_config ->", json.dumps(res))
    sys.exit(0 if res["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
