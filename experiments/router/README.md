# experiments/router

Spec 0001's empirical harnesses **and the router itself** (`darkcore/`).

## dark-core — the data-plane router (v0, 2026-07-16)

`darkcore/` is the standalone router: prefilter → (predictor, auto-off at n=0)
→ cascade(verify+escalate), actuated only through the control surface
(`darkcore/surface.py` == `specs/0001/control-surface.md` v1), telemetry to
`logs/router/*.jsonl` (PII rule: hash + features, never content).

```bash
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python   # has mlx_lm + rich
cd experiments/router

$MLXPY -m darkcore.cli route "your query"        # route one query
$MLXPY -m darkcore.cli config get                # the control surface
$MLXPY -m darkcore.cli config patch '{"lambda_by_class":{"agentic":0.45}}' --base 2 --actor operator
$MLXPY -m darkcore.cli state                     # live_metrics rollup

$MLXPY -m darkcore.tui                           # gauge board: snapshot
$MLXPY -m darkcore.tui --live                    # follow the router live
$MLXPY -m darkcore.tui --replay --speed 8        # replay telemetry history
```

- `battery.jsonl` — the labeled n=6 battery + 6 unlabeled probes (bench input,
  future kNN seed exemplars).
- `darkcore_bench.py` — full battery through the real cascade + T2-only
  baseline → `report.json` (+ per-answer snapshots in `bench-answers/`).
- `verify.py` — asserts prd.md success criteria against `report.json`
  (`--assert-thresholds`; `--run` to re-bench first).
- Findings report: **`BENCH-REPORT.md`**.

## Closure harnesses (the numbers the design rests on)

- `closure.py` — Exp 1 embedder/V2 (P1), Exp 2 verifiers vs real T0/T1 outputs,
  Exp 3 λ sweep. Needs torch+transformers (same mlx-lm env), bge-small in HF cache.
- `swap_econ.py` — Exp 4 swap economics: per-tier load/TTFT/decode, T0+T1
  co-residency. Raw datapoints: `swap-econ.results.jsonl`.
- `fixtures/` — captured T0/T1 outputs used by Exp 2.

Full writeups: `../../specs/0001-tiered-cascade-router/results.md` (Exp 1–4).
Headlines: **P1** (embeddings see class, not difficulty; LOO 0.33 < 0.67
baseline) and **Exp 4** (swap ≈ 10% of a T2 generation → the cascade's
economics survive; T0+T1 co-reside free).
