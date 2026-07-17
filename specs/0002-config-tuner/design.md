# Spec 0002 — Design: config tuner

## Shape

One batch pipeline, five pure-ish stages, one commit point:

```
logs/router/*.jsonl ─┐
                     ├─▶ ingest ─▶ provenance gate ─▶ snapshot build ─▶ report ─▶ [operator] ─▶ publish
darkcore/candidates/ ┘   (join)     (label ladder)     (v<N+1>, off       (evidence           (set_config,
                                                        to the side)       per change)          ref swap)
```

- Everything left of **publish** is side-effect-free w.r.t. the router:
  snapshots are built in a fresh `exemplars/v<N+1>/` dir; config untouched.
- **Publish is the only commit point** — one `set_config` patch riding the
  surface's atomic rename + optimistic concurrency (`base_version` read at
  ingest; drift → `conflict` → re-run, never force).
- Crash anywhere ⇒ at worst an orphaned unref'd snapshot dir (GC'd next run).

## 1. Ingest (`ingest.py`)

Joins two sources on `route_id`:

- **Telemetry** (`logs/router/*.jsonl`): `routing_decision` (class, prefilter
  fires, config_version), `verifier_result` (rung, verdict, check),
  `route_completed` (attempts, smallest_sat via per-attempt outcomes,
  final_tier, flagged), `escalation`.
- **Candidate buffer** (`darkcore/candidates/`, written by the router at
  route time — prd T1): the query **embedding** + qhash per predictor-run
  route. Required because telemetry is hash+features only (PII rule) —
  production text is gone forever; the embedding captured in-path is the
  only admissible representation.

Output: candidate records
`{route_id, qhash, embedding, embedder_id, class_signals, per_attempt:
[{tier, rung, verifier, verdict}], smallest_sat, flagged, config_version}`.

## 2. Provenance gate (`provenance.py`) — the label ladder

The certificate problem, propagated: a label is only as good as its
verifier. Policy per rung, decided **separately for class labels vs tier
labels** (prd D2 — class is about *what the query is*, cheap to trust; tier
is about *what quality was achieved*, exactly what cheap verifiers get wrong):

| Ladder | Source rung | Class label | Tier label (`smallest_sat`) |
|---|---|---|---|
| **L0** | 0–1 (certificate: nesting/arg-shape, plugback) | admit | **admit** (certificate-backed) |
| **L1** | 4 (next-tier judge) | admit | **quarantine** — needs corroboration: ≥2 concordant traces, or 1 + agreement with the class's battery-labeled tier; until then influences nothing |
| **L2** | 5 (fixed policy, never verified) | admit *only if* prefilter and embedder agreed | **refuse** — no self-labeling; the future label source is 0003's sampled inspection |

Unconditional inadmissibility (before the ladder even applies), each with a
logged receipt (S3):

- `flagged` routes (terminal failure — nothing to learn except for 0003);
- answer fails **extraction hygiene** (prd T2 — the Bonsai-27B CoT-as-prose
  leak; a poisoned answer must not become a labeled exemplar);
- `embedder_id` ≠ the store's pinned embedder (prd D4);
- near-duplicate of an existing exemplar (cos ≥ SELF_SIM 0.995 — the store
  must densify coverage, not re-count one query);
- a rung-4 label later **contradicted** by an escalation of a concordant
  trace (contradiction evicts the whole quarantine group back to pending).

The gate is pure logic over ingest records + current snapshot meta — fully
fixture-testable without models (verify.py S1/S3).

## 3. Snapshot build (`snapshot.py`)

Generalizes `seed_exemplars.py`. `exemplars/v<N+1>/` =
`embeddings.npy` (seed corpus rows re-used verbatim + admitted candidate
rows appended — production rows are **never re-embedded**, they ship the
in-path embedding) + `meta.json` extended per-exemplar with provenance:

```jsonc
{ "version": N+1, "embedder": "BAAI/bge-small-en-v1.5", "n": ...,
  "ids": [...], "classes": [...], "query_hashes": [...],
  "tier_labels": [...],            // null where refused/quarantined (D2)
  "provenance": [                  // parallel array, one per exemplar
    {"source": "seed", "origin": "battery.jsonl"},
    {"source": "trace", "route_id": "...", "rung": 0, "verdict": "pass",
     "ladder": "L0", "config_version": 3}
  ],
  "content_hash": "...", "parent_version": N }
```

Immutable once written; the ref swap is the commit; tuner keeps last K for
rollback (`cli.py rollback` = re-publish an old ref, journaled).

## 4. Recalibrators (`recalibrate.py`) — evidence in, proposals out

Each reads the ingested corpus, emits `{knob, current, proposed, evidence,
n_evidence}` into the report — **none auto-applies in v1**, and each stays
silent below its minimum-evidence n (open item 3):

- **start-map:** per class, the `smallest_sat` distribution vs current
  start; propose a raise only when the escalation tax measurably dominates
  the risk of overshooting (the E1/E2-style receipts).
- **verifier thresholds:** verdict-vs-outcome receipts (rung-0 passes later
  contradicted, judge false-accepts caught by re-escalation).
- **λ sweep:** offline replay over labeled exemplars, per-class utility
  = quality − λ·cost; firms the directional 0.40/0.35/0.20.

## 5. Publish (`publish.py`) + report (`report.py`) + CLI

- `tuner run` → tune report (JSON + rendered text): counts per
  admit/reject/quarantine reason, snapshot diff (n, per-class), proposed
  patch, evidence per knob, the `base_version` it was computed against.
- `tuner apply <report>` → one `set_config` patch (`actor: "tuner"`,
  note = report ref). `conflict` → exit nonzero, say so, never retry-force.
  `invalid` → a tuner bug by definition (bounds are known) — loud failure.
- Telemetry `logs/tuner/<date>.jsonl` per repo standard: `tune_started`
  (inputs, config_version, corpus counts), `candidate_admitted`/
  `candidate_rejected` (reason, ladder), `snapshot_built` (version, n,
  content_hash), `patch_proposed`, `patch_applied`/`patch_conflict`,
  `tune_completed` (wall, peak RSS). qhash/route_id only — no content.

## Failure modes (expected, with posture)

- **F1 — Judge self-confirmation loop.** Rung-4 labels come from tier
  models the tuner is tuning; a drifted judge could launder its own bias
  into the corpus. *Posture:* L1 quarantine + battery-agreement check +
  contradiction eviction; the battery (ground truth) never leaves the
  corpus and anchors every sweep. *Residual:* real — revisit when 0003's
  inspection provides an independent label channel.
- **F2 — Distribution capture.** Production traffic skew (e.g. all
  agentic) grows one class's exemplar mass and starves others; kNN votes
  tilt. *Posture:* per-class caps relative to seed proportions in v1;
  report shows class balance drift.
- **F3 — Embedder migration wipes production exemplars** (prd D4). Not a
  bug — a recorded consequence. Mitigation is sequencing: mlx-port the
  embedder while n is small.
- **F4 — Buffer loss ≠ harm.** Candidate buffer is best-effort; losing it
  loses learning material, never correctness. Router never blocks on it.

## Out of scope (restated)

Bandit/RL (after the corpus earns trust), orchestrator knobs, request-path
anything, labeling UI.

## References

`../0001-tiered-cascade-router/control-surface.md` (§2 ops, §4 invariants,
§5 store, §8 ownership) · `seed_exemplars.py` (the prototype) ·
`darkcore/predictor.py` (SELF_SIM, class-prior consumer) ·
0001 `decisions.md` D6/P1/P2/V-struct · architecture doc §5, §11.
