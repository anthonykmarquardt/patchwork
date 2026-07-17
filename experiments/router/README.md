# experiments/router

Empirical-closure harness for **spec 0001** (the tiered cascade router). Not the
router itself — this is the throwaway experiment that produced the numbers the
spec's design decisions rest on.

## Contents

- `closure.py` — runs the three closure experiments on the n=6 battery:
  - **Exp 1** embedder/V2 — bge-small locality + leave-one-out tier prediction.
  - **Exp 2** verifiers — per-class checks vs the real captured T0/T1 outputs.
  - **Exp 3** λ sweep — `utility = quality − λ·cost`, per class.
- `fixtures/` — the captured model outputs used by Exp 2 (Bonsai 1.7B/8B ternary,
  reasoning-agentic and emotional batteries), as `bonsai-<size>-ternary.<battery>.txt`.

## Run

Needs a python with `torch`+`transformers`+`numpy` (the mlx-lm uv-tool env);
`BAAI/bge-small-en-v1.5` must be in the HF cache.

```bash
$HOME/.local/share/uv/tools/mlx-lm/bin/python experiments/router/closure.py
```

## Findings (summary)

n=6 is the cold-start regime, so Exp 1/3 are directional and Exp 2 (real failure
outputs) closes cleanly. Full writeup: `../../specs/0001-tiered-cascade-router/results.md`.
Headline: **P1** — embeddings cluster by *class*, not *difficulty* (LOO tier
accuracy 0.33 < 0.67 baseline). Verifier config and per-class λ settled there.
