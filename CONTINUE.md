# Patchwork — CONTINUE.md

> **Handoff snapshot.** Read this first when resuming work in a new session.
> **Rule:** Overwrite at end of session. Never append. This is a snapshot, not a history.

---

## Bootstrap Sequence (Do This First, In Order)

```bash
cd ../patchwork
git status                              # expected: untracked/modified darkcore work (uncommitted as of writing)

# THE conceptual entry point:
cat docs/routing-architecture.md

# What happened last session (v0 build + bench):
cat experiments/router/BENCH-REPORT.md

# Watch the bench replay on the gauge board (recommended, ~1 min at speed 20):
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python
cd experiments/router && $MLXPY -m darkcore.tui --replay --speed 20
```

---

## Current Status

**dark-core v0 EXISTS and is benched.** The routing pillar went from
paper-only to a running data plane this session (2026-07-16):

- `experiments/router/darkcore/` — prefilter → cascade(verify+escalate),
  swap-aware model pool (T0+T1 co-resident), verifier registry (rungs 0/1/4;
  emotional = rung-5 → D5 floor), PII-safe JSONL telemetry, CLI, and the
  **gauge board TUI** (`darkcore/tui.py`, Catppuccin Frappé, snapshot/--live/--replay).
- **Control surface FIRMED (v1) + implemented** (`specs/0001/control-surface.md`
  ↔ `darkcore/surface.py`): file transport + atomic rename, invariants I1–I10,
  optimistic concurrency, patch journal, hot reload. **0002/0003 are now
  unblocked** — they were gated on this schema.
- **Exp 4 (swap economics) measured** — results.md §Exp 4: cascade survives its
  falsification test; swap ≈ 10% of one T2 generation; T0+T1 co-reside free.
- Spec 0001 stays `draft`: predictor posture still open + S1 fails (below).

## Bench headlines (full: experiments/router/BENCH-REPORT.md)

- **1.66× vs T2-only**, 83% of routes ≤T1, escalation rate 0.33, overhead 0.05 ms.
- **Safety works:** R1 (confidently-wrong T0) caught twice, landed T2 (S2 ✓).
- **S1 quality retention FAILS** (0.792 vs 0.992, ε 0.15) — sole cause: rung-0
  **V-struct false-accept** on agentic (A1: well-formed calls, absurd semantics).
- **Cost decomposition: swap 0.5% · gen 73% · judge 26%** — the feared cost
  (swap) is dead; the real tax is the rung-4 judge (C2 confirmed).
- **P-class miss live-confirmed (E3):** lexicon missed "furious" → no D5 floor
  → T0 listicle → T1 judge passed it. One gap defeated three defenses.
- Bonsai-27B narrates CoT without `<think>` tags → leaks into answers.

## What's Next (Prioritized)

1. ~~Agentic rung-0 semantics layer~~ — **DONE (bench v0.1, later this same
   date): ALL THRESHOLDS PASS** (S1 0.900 vs 0.842; speedup 1.72×; A1 now
   T0✗→T1✓; v0 snapshot kept as `report-v0.json`).
2. **Layer arbitration → embedder owns class.** E3 is the proof of need; Exp 1
   showed class-locality is what embeddings do well. Prefilter keeps floors.
3. **Plan 0002 (tuner) + 0003 (orchestrator)** — unblocked by the firmed
   surface; every bench recommendation is a control-surface patch a tuner could
   learn. 0003's attention budget + 0002's label provenance are the hard cores.
4. **Judge economics:** skip_start for judge-chain classes; per-tier judge
   token caps.
5. Phase 0 corpus (exemplars at n ≫ 6) → predictor posture → spec 0001 `ready`.

## Open Questions / Blockers

- Predictor posture (unchanged; needs the corpus).
- **Uncommitted work:** the entire darkcore build + doc updates from this
  session need a commit (operator hadn't asked; nothing pushed).

## Gotchas

- Run darkcore/TUI **from `experiments/router/`** with the mlx-lm uv-tool
  python (`$MLXPY` above) — package is not installed, imported by cwd.
- Only T2 needs the box alone; **T0+T1 co-reside safely** (2.93 GB, Exp 4).
- Thinking-tier T2 needs ≥1000 completion tokens (roster ships 1536) **and**
  narrates CoT as prose (no `<think>` tags) — answer extraction is imperfect.
- Bench answers (raw text) live in `experiments/router/bench-answers/` — a
  bench artifact, NOT logs; telemetry itself is hash+features only (PII rule).
- `config.json` is at config_version 2 (two smoke-test journal entries); the
  journal is the audit trail (`config.journal.jsonl`).
- Eval substrate lives in **spark**: `spark/MODEL-EVAL-2026-07-15.md`,
  `spark/bake-offs/`, `spark/spikes/human-emotion-eval-skill.md`.
