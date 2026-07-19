#!/usr/bin/env python3
"""Embedder parity harness — torch bge-small vs the mlx port.

Two phases, one fixed text set (battery 12 + authored seeds 9 + edge probes):

  uv run python embedder_parity.py capture   # BEFORE the port, torch env:
      writes fixtures/embedder-parity/{texts.json, torch.npy, timings.json}
  uv run python embedder_parity.py check     # AFTER the port:
      embeds the same texts with darkcore.embedder_mlx, gates on
      min cosine >= 0.9999 and identical kNN neighbor ordering,
      reports warm-latency comparison against the captured torch numbers.

The captured torch.npy is the frozen reference — regenerating it after
torch leaves pyproject means reinstalling torch, so it is committed.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

OUT = os.path.join(HERE, "fixtures", "embedder-parity")
MODEL_ID = "BAAI/bge-small-en-v1.5"
COS_GATE = 0.9999
N_TIMING_REPS = 50

# Edge probes: shapes the battery doesn't cover (short, long, unicode, code).
EDGE_PROBES = [
    ("EP1", "hi"),
    ("EP2", "?"),
    ("EP3", "def f(x):\n    return x ** 2  # naïve càché ünïcode π ≈ 3.14159"),
    ("EP4", "word " * 600),  # > max_length=512 tokens — truncation path
    ("EP5", "Explain the difference between TCP slow start and congestion "
            "avoidance, then write a haiku about packet loss."),
]


def load_texts():
    rows = []
    for fname in ("battery.jsonl", "exemplar-seeds.jsonl"):
        for line in open(os.path.join(HERE, fname)):
            if line.strip():
                r = json.loads(line)
                rows.append((r["id"], r["query"]))
    rows.extend(EDGE_PROBES)
    return rows


def capture():
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.set_num_threads(1)  # match predictor.py's runtime posture
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    mdl = AutoModel.from_pretrained(MODEL_ID).eval()

    def embed(text):
        with torch.no_grad():
            enc = tok([text], padding=True, truncation=True,
                      max_length=512, return_tensors="pt")
            e = mdl(**enc).last_hidden_state[:, 0]
            return torch.nn.functional.normalize(e, dim=1).numpy()[0]

    rows = load_texts()
    E = np.stack([embed(q) for _, q in rows]).astype(np.float32)

    embed("warmup")
    t0 = time.perf_counter()
    for _ in range(N_TIMING_REPS):
        embed(rows[0][1])  # XA1: a mid-length battery query
    warm_ms = (time.perf_counter() - t0) * 1000 / N_TIMING_REPS

    os.makedirs(OUT, exist_ok=True)
    np.save(os.path.join(OUT, "torch.npy"), E)
    json.dump({"ids": [i for i, _ in rows], "texts": [q for _, q in rows]},
              open(os.path.join(OUT, "texts.json"), "w"), indent=1)
    json.dump({"runtime": "torch", "torch_version": torch.__version__,
               "threads": 1, "warm_ms_mean": round(warm_ms, 3),
               "reps": N_TIMING_REPS, "timing_text_id": rows[0][0],
               "captured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              open(os.path.join(OUT, "timings.json"), "w"), indent=1)
    print(f"captured {E.shape} reference vectors; torch warm embed "
          f"{warm_ms:.2f} ms (n={N_TIMING_REPS})")


def check():
    from darkcore.embedder_mlx import MlxEmbedder

    ref = np.load(os.path.join(OUT, "torch.npy"))
    meta = json.load(open(os.path.join(OUT, "texts.json")))
    baseline = json.load(open(os.path.join(OUT, "timings.json")))

    emb = MlxEmbedder(MODEL_ID).warm()
    E = np.stack([emb.embed(q) for q in meta["texts"]]).astype(np.float32)

    cos = (E * ref).sum(axis=1)  # both rows are L2-normalized
    worst = int(np.argmin(cos))
    print(f"cosine: min {cos.min():.6f} (id {meta['ids'][worst]}), "
          f"mean {cos.mean():.6f}")

    # kNN ordering: for each battery/seed vector, neighbor order over the
    # full reference set must match between runtimes (what classify() sees).
    order_ok = all(
        np.array_equal(np.argsort(-(ref @ ref[i])), np.argsort(-(E @ E[i])))
        for i in range(len(cos))
    )
    print(f"kNN neighbor ordering identical: {order_ok}")

    emb.embed("warmup")
    t0 = time.perf_counter()
    for _ in range(N_TIMING_REPS):
        emb.embed(meta["texts"][0])
    warm_ms = (time.perf_counter() - t0) * 1000 / N_TIMING_REPS
    print(f"warm embed: mlx {warm_ms:.2f} ms vs torch "
          f"{baseline['warm_ms_mean']:.2f} ms "
          f"({baseline['warm_ms_mean'] / warm_ms:.1f}x)")

    ok = cos.min() >= COS_GATE and order_ok
    print("PARITY: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["capture", "check"])
    args = ap.parse_args()
    sys.exit(capture() if args.phase == "capture" else check())
