# Patchwork — CONTINUE.md

> **Handoff snapshot.** Read this first when resuming work in a new session.
> **Rule:** Overwrite at end of session. Never append. This is a snapshot, not a history.

---

## Bootstrap Sequence (Do This First, In Order)

```bash
cd ../patchwork
git status && git log --oneline -5      # expect dark-core v0.2 commits at HEAD, clean tree

# THE conceptual entry point:
cat docs/routing-architecture.md

# The JOURNEY — evidence→decision→next-step chain, episodes 1–6 (read 2nd):
cat specs/0001-tiered-cascade-router/journal.md

# The bench findings (v0 → v0.1 → v0.2 comparison up top):
cat experiments/router/BENCH-REPORT.md

# Watch it happen on the gauge board (~2 min):
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python
cd experiments/router && $MLXPY -m darkcore.tui --replay --speed 30
```

---

## Current Status (2026-07-17)

**dark-core v0.2: built, benched three times, steps 1–3 of the backlog done.**

- **Predictor live in class-prior mode** (`darkcore/predictor.py`): bge-small
  kNN over an immutable exemplar snapshot (n=21), published through the
  control surface (config **v3**, journaled). Class detection **12/12**;
  the E3 emotional miss is fixed with a receipt. Arbitration pinned:
  rules-when-they-fire > embedder > abstain-to-default.
- **Rung-0 verifier** now: nesting + arg-shape + **inconclusive→judge
  fallthrough** (a certificate with nothing to certify is not a pass).
- **Judge caps** (T1 256 / T2 512 tokens) + **skip_start** for unclassifiable
  queries; judge tax 26.2% → 24.5%.
- **Escalation visibility**: `route(query, on_event=...)`; CLI streams
  `◉ ✓ ✗ ➜` status on stderr.
- **Bench v0.2 final:** quality 0.900 (S1 ✓), safety stable ×3 (S2 ✓),
  83% ≤T1 (S3 ✓), observability ✓ — **S4 FAILS by 2.36 ms** (22.36 vs 20 ms
  worst-route overhead; see decision below).

## THE OPEN DECISION (operator input needed before spec 0001 → ready)

**S4 budget.** The 27B's residency pages out the embedder; mitigations applied
(single-thread torch, init warmup, causally-honest rewarm at the evicting
route's tail — telemetered `prior_rewarmed`), worst residual 22.36 ms vs the
20 ms budget. Options: **(a)** keep 20 ms absolute → pin embedder memory or
port it to mlx; **(b)** restate S4 as *overhead < 1% of route cost* (worst
measured: 0.008% on its route; ≤0.8% on the cheapest route). Iteration was
stopped deliberately — don't chase page-cache noise without deciding this.

## What's Next (Prioritized)

> Derivations: journal.md Episode 6 tail. Bench snapshots:
> report-v0 / v0.1 / v0.2-rc1 / v0.2-rc2 / report.json (final).

1. **S4 budget decision** (above) — small, unblocks `ready` for spec 0001.
2. **Plan 0002 (tuner).** `seed_exemplars.py` literally performed the tuner's
   job by hand (build snapshot → publish via set_config): write the spec from
   this working example. Hard core: label provenance (journal + decisions.md).
3. **Plan 0003 (orchestrator).** Hard core: the attention budget. Alarm feed
   exists (`terminal_failure`, `budget_exhausted`); silent-failure sampling
   does not yet.
4. **Phase-0 exemplar corpus** (n ≫ 21) → tier prediction posture → recalibrate
   λ (still unused: predictor abstains from tiers at low n).
5. Residual seams (attack via tuner, not more rules): rung-0 blind to strategy
   (A4); Bonsai-27B CoT-as-prose leaks into answers (would poison exemplar
   labels — fix answer extraction before the growth loop ships).

## Gotchas

- Run darkcore/TUI **from `experiments/router/`** with the mlx-lm uv-tool
  python (`$MLXPY`). Config is at **v3** (predictor on, skip_start on).
- Re-seeding exemplars: `seed_exemplars.py` bumps the snapshot version — it
  will `conflict` if config moved; read current version first (by design).
- **The 27B evicts the embedder** (the S4 saga) — any new resident component
  must assume T2 wipes the page cache; put rewarms at the evicting route's
  tail, and never trust solo latency measurements on this box.
- T0+T1 co-reside safely; only T2 needs the box alone (Exp 4).
- Thinking-tier T2: ≥1000 completion tokens or empty answers; narrates CoT
  without `<think>` tags.
- Bench answer snapshots: `experiments/router/bench-answers/` (bench artifact,
  not logs; telemetry stays hash+features per the PII rule).
- Eval substrate lives in **spark**: `spark/MODEL-EVAL-2026-07-15.md`.
