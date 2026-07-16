# Spec 0001 — Test plan / minimum expected verifiers

## Verifier command (declared in status.yaml)

```bash
python experiments/router/verify.py \
  --battery experiments/router/battery.jsonl \
  --report  experiments/router/report.json \
  --assert-thresholds
```

Run from `../patchwork/`. Deterministic (fixed seeds, temp 0 for any
model call). Exits non-zero if any threshold in §Acceptance fails.

## Minimum expected verifiers

The definition of done requires **all** of the following to pass. Each maps to a
success criterion in the PRD.

### V1 — Prefilter determinism (unit)
Given a fixed set of labeled prompts, `prefilter.py` returns identical
`{route_hint, floor, reason}` across runs, with no model call and no I/O.
- *Pass:* deterministic output; agentic/emotional/trivial fixtures classified as
  specified; ambiguous → `None`.
- *Fail:* any nondeterminism or a network/model call in the prefilter path.

### V2 — Predictor accuracy (held-out)
kNN tier prediction on a held-out slice of the battery (e.g. 80/20 split).
- *Pass:* predicted-tier accuracy ≥ a floor set on the validation slice **and** ≥ a
  majority-class baseline by a stated margin; k and λ recorded in the report.
- *Fail:* below baseline, or the index requires retraining to add a tier.

### V3 — Cascade safety (the load-bearing test)
A **confidently-wrong fixture**: a T0-answerable-looking prompt where T0 is known to
produce a fluent-but-wrong answer (e.g. the R1 "missing dollar" trap).
- *Pass:* the verifier **rejects** T0's output and the cascade **escalates**; the
  final emitted answer is correct (from T1/T2), and the trace shows the escalation.
- *Fail:* a confidently-wrong T0 answer is emitted, or the verifier passes it.

### V4 — Cost/quality retention (end-to-end)
Run the full battery through `route()`.
- *Pass:* aggregate answer quality ≥ (T2-only − ε) **and** ≥ 60% of queries resolved
  at T0/T1 (i.e. real cost savings), per `report.json`.
- *Fail:* quality below the T2 floor, or everything escalates to T2 (router adds cost
  with no benefit).

### V5 — Extensibility smoke
Add a synthetic 4th tier by dropping exemplars into `battery.jsonl` and rebuilding
the index only.
- *Pass:* the new tier becomes selectable with **no code change and no retrain**.
- *Fail:* adding a tier requires touching predictor code or a training step.

### V6 — Router latency budget
Measure prefilter + embed + kNN lookup wall-time per query on the M2.
- *Pass:* < 20 ms/query median (excluding the actual model generation).
- *Fail:* ≥ 20 ms — the router overhead defeats the point at T0 scale.

## Report artifact

`report.json` must contain, per query: predicted tier, prefilter hint, tiers tried,
verifier verdicts, final tier, quality score, and router-overhead ms; plus the
aggregate rollups V2/V4/V6 assert against. The report is the reproducible evidence.

## Notes on fairness / hygiene (carried from this session)

- One tier resident at a time when measuring; watch memory pressure — the 27B (T2)
  thrashes on the 16 GB M2 if the machine isn't clean (discard contaminated runs).
- Any thinking-tier model (T2, or Ornith at T1) needs ≥1000 completion tokens or it
  returns an empty answer; budget accordingly in the harness.
