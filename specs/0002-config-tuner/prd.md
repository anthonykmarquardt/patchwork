# Spec 0002 — Config tuner (control plane)

> Planned 2026-07-17 from the working example: `seed_exemplars.py` performed
> the tuner's job by hand (build immutable snapshot → publish via one
> `set_config` patch). This spec turns that hand-run into a closed, gated,
> auditable loop. Read `../../docs/routing-architecture.md` (§3, §5, §11) and
> `../0001-tiered-cascade-router/control-surface.md` first.

## Problem

The router (0001, `ready`) runs dark-operable on a hand-seeded config:
n=21 exemplars, directional λ (0.40/0.35/0.20), verifier thresholds tuned
against one bench, class start-map set by judgment. Every one of those
parameters is *measurable from telemetry the router already emits* — but
nothing consumes that telemetry. The predictor abstains from tier prediction
until n grows (P2 cold-start); λ was never swept on real volume; the start
map ignores the measured `smallest_sat` distribution. The knowledge to
improve the router accumulates in `logs/router/` and dies there.

The naive fix — "learn from the logs" — runs straight into the **certificate
problem propagated into the learning loop**: telemetry labels are only as
trustworthy as the verifier that produced them. Rung 0–1 verdicts are
certificates; rung-4 verdicts are one model's opinion of another; rung-5
classes (emotional) are *never verified at all*. A tuner that treats these
alike will confidently poison its own exemplar store.

## Role — the configuration/learning half of the control plane

Out-of-band, **asynchronous, never in the request path**. Per-dispatch
batch process (`tuner run`), not a daemon — cross-session learning off the
accumulating store. It acts **only through the control surface**
(surface §8: `lambda_by_class`, `verifier_config`, `class_start_map`,
`prefilter_rules`, and as **sole writer** of `exemplar_store_ref` /
`predictor_enabled`). It never touches orchestrator knobs (`class_floor`,
`cascade_policy`, `escalation_overrides`, `tier_roster`). The router keeps
zero hard dependency on it (dark-operability is preserved by construction).

## Goals

1. **Exemplar growth loop (the core).** Turn production traces into labeled
   exemplars — *gated on label provenance* — and publish immutable snapshots
   v2, v3, … exactly as `seed_exemplars.py` did for v1. Growing n is what
   unlocks tier prediction (P2) and the difficulty-predictor reconsideration
   (taxonomy A, arXiv:2511.03808).
2. **Provenance-tiered label admission.** A label ladder with per-rung trust
   policy (see design.md): certificate labels auto-admit; judge labels admit
   quarantined with corroboration; unverifiable classes are **refused** —
   the tuner declines to tune what it cannot trust (safe default until 0003's
   sampled inspection exists as a label source).
3. **Recalibration from measurement.** `class_start_map` from the measured
   `smallest_sat` distribution; verifier thresholds from verdict-vs-outcome
   receipts; λ re-swept offline on the grown corpus (firm the directional
   0.40/0.35/0.20).
4. **Propose-then-apply actuation.** v1 is operator-gated: `tuner run`
   produces a tune report (candidate patch + snapshot + evidence per change);
   `tuner apply` publishes via `set_config` with optimistic concurrency.
   Autonomy widens later, knob by knob, with bounds — never all at once.
5. **Observability parity.** The tuner is itself a `..` process:
   JSONL telemetry (`component: tuner`, `logs/tuner/`), every applied patch
   journaled with `actor: tuner` and an evidence note. A tune must be as
   reconstructable as a route. No black box.

## Out of scope

- **RL / bandit policy learning** (taxonomy C — Router-R1 style). Deferred
  until the batch loop has a trustworthy corpus; the bandit inherits every
  provenance problem this spec solves, so it comes after, not first.
- **Supervisory duties** — alarms, volitional inspection, floors, roster
  (0003 orchestrator).
- **Anything in the request path.** The tuner's absence, crash, or slowness
  must be invisible to `route()`.
- **Difficulty prediction** itself (it's a *consumer* of the corpus this
  spec builds).
- Human-labeling UI. v1's operator gate is the CLI report; a review queue
  for rung-5 samples arrives with 0003.

## Success criteria

- **S1 — Growth with receipts.** Against the real v0.2 telemetry + battery,
  one `tuner run` produces snapshot v2 with n > 21 where **every admitted
  exemplar is traceable** (trace id, verifier rung, verdict, config_version
  in the snapshot manifest) and every rejected candidate logs a reason.
- **S2 — Safe by construction, exercised.** The tuner writes only its own
  knobs; adversarial fixture patches (orchestrator knobs, invariant
  violations I1–I10, stale `base_version`) are refused with zero partial
  application. Crash mid-run leaves config and store untouched (snapshot
  build is off to the side; the ref swap is the only commit point).
- **S3 — No poison.** Planted bad candidates are *not* admitted: a
  CoT-leak-style malformed answer (the Bonsai-27B prose leak), a rung-4
  label contradicted by a later escalation, a rung-5 trace, an
  embedder-version mismatch. Each rejection carries a receipt.
- **S4 — Measured improvement, never regression.** With snapshot v2 + tuned
  config: class-prior accuracy on held-out probes ≥ v1's 15/15 baseline
  set, and a re-bench (`--empirical`) holds S1/S2/S3 of spec 0001 (quality
  ≥ 0.900 − ε, safety catch intact, ≥T1 share ≥ 60%). A tune that degrades
  the bench is auto-rolled-back material, not a pass.
- **S5 — Observability complete.** From `logs/tuner/` + the config journal
  alone: what ran, what it read, what it admitted/rejected/why, what it
  proposed, what was applied, and which evidence backed each knob change.
- **S6 — Dark-operability preserved.** Router behavior is bit-identical with
  the tuner absent; `predictor_enabled`/store invariants (I8) hold through
  every publish.

## Task checklist

- [ ] **T1 — Candidate buffer (0001-side addendum, gates everything).**
      The PII rule (hashes + features, never raw text) means production
      queries can never be re-embedded after the fact — so the router must
      emit the embedding *at route time*. Add a bounded sidecar buffer
      (`darkcore/candidates/`): per route where the predictor ran, append
      {embedding row, qhash, class, prefilter fires, per-attempt verdicts +
      rungs, smallest_sat, config_version, route_id}. Embeddings-not-text
      matches the snapshot store's existing PII posture. Bounded (ring, size
      cap), GC'd after tuner consumption. Owner note: this is a data-plane
      emit, kept dumb — admission logic lives entirely in the tuner.
- [ ] **T2 — Answer-extraction poison guard (prerequisite for T2-derived
      labels).** Bonsai-27B narrates CoT as prose into answers; a candidate
      whose answer fails extraction hygiene is inadmissible (else the leak
      poisons labels). Detector + receipt; ships before any T2-sourced
      admission.
- [ ] **T3 — Tuner package** (`experiments/router/tuner/`): `ingest.py`
      (telemetry + candidate-buffer reader), `provenance.py` (the label
      ladder, pure logic), `snapshot.py` (generalize `seed_exemplars.py`:
      build v<N+1> from admitted set + seed corpus, content-hashed manifest
      with per-exemplar provenance), `publish.py` (`set_config` wrapper:
      conflict/invalid handling, evidence note), `report.py`, `cli.py`
      (`run` / `apply` / `rollback`).
- [ ] **T4 — Recalibrators**: start-map from `smallest_sat` per class
      (with minimum-evidence n per class before proposing); threshold
      recalibration from verdict-vs-escalation receipts; offline λ sweep on
      the grown corpus. Each emits evidence into the tune report; none
      auto-applies in v1.
- [ ] **T5 — Verifier harness** (`experiments/router/tuner/verify.py`):
      deterministic fixtures for S1/S2/S3/S5/S6 (no model inference —
      admission logic is pure); `--empirical` flag re-runs the 0001 bench
      for S4. Fixtures include the planted-poison set.
- [ ] **T6 — Telemetry + docs**: `logs/tuner/` per the repo logging
      standard; tune-report artifact format; journal.md episode on first
      real tune.

## Resolved design decisions (proposed — full rationale in design.md)

- **D1 — Provenance ladder** L0 (rung 0–1 certificates: auto-admit) /
  L1 (rung 4 judge: quarantine + corroboration before influence) /
  L2 (rung 5: refuse-to-tune; future label source is 0003's sampled
  inspection, not self-labeling).
- **D2 — Class labels vs tier labels are admitted separately.** Class
  admission is cheap and safe at all rungs (class ≠ quality); tier labels
  (`smallest_sat`) demand the ladder. This lets n grow fast for the class
  prior while tier prediction waits for trustworthy volume — matching the
  predictor's current class-only posture.
- **D3 — Propose-then-apply; autonomy per knob, later.** The control
  surface makes wider autonomy a policy change, not a code change.
- **D4 — Embedder identity is part of the corpus contract.** Snapshot meta
  already pins `embedder`; the tuner enforces candidate/store embedder
  match (mismatch = inadmissible, S3). **Consequence:** migrating the
  embedder (the planned mlx port of bge-small) invalidates all
  production-derived exemplars — raw text was never kept, so they cannot be
  re-embedded. *Do the mlx port before the corpus gets big, or pay a
  corpus reset.* This sequencing pressure is recorded in CONTINUE.md.
- **D5 — Not a daemon.** Per-dispatch batch, same posture as
  merge-coordinator; T1-transport (file surface) already supports it.

## Open items (settle before `ready`)

1. **Operator sign-off on the ladder (D1)** — especially L1 corroboration
   (proposed: a rung-4 tier label needs ≥2 concordant traces, or 1 trace +
   agreement with the class's battery-labeled tier, before it can shift the
   start-map evidence; class labels exempt per D2).
2. **T1 buffer shape** — ring size / retention / GC handshake, and whether
   `route_completed` gains a `candidate_emitted` flag (observability of the
   growth loop itself). Embedding-inversion risk is acknowledged: buffer is
   local, bounded, GC'd; same trust domain as the snapshot store.
3. **Minimum-evidence thresholds** for recalibrators (per-class n below
   which the tuner stays silent) — propose after first ingest of real
   volume, from the report's own counts.
4. **S4 ε** for the empirical re-bench (propose: reuse spec 0001's
   EPS=0.15 against its own baseline).

## References

- `../0001-tiered-cascade-router/control-surface.md` — the contract (§5
  snapshot store, §8 knob ownership) — **firm, v1**
- `../0001-tiered-cascade-router/decisions.md` — D6 (exemplar-growth loop,
  relocated here), P1/P2, V-struct
- `../../experiments/router/seed_exemplars.py` — the hand-run prototype of
  this entire spec
- `../../experiments/router/BENCH-REPORT.md` — judge tax 24.5% (the skip
  of doomed attempts is this spec's payoff), E3 receipt (class detection →
  embedder), S4 resolution
- `../../docs/routing-architecture.md` §5 (taxonomy C deferred here), §11
  (the open problem this spec closes)
- `../CLAUDE.md` — Runtime Logging standard + PII rule (both binding on
  the tuner itself)
