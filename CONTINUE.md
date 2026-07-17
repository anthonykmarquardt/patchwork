# Patchwork — CONTINUE.md

> **Handoff snapshot.** Read this first when resuming work in a new session.
> **Rule:** Overwrite at end of session. Never append. This is a snapshot, not a history.

---

## Bootstrap Sequence (Do This First, In Order)

```bash
cd ../patchwork
git status                              # expected: clean
git log --oneline -8                    # expect the "0001-0003 router architecture handoff" commits at HEAD

# THE conceptual entry point — read before touching any spec:
cat docs/routing-architecture.md

# The active workstream:
ls specs/                               # 0001 (router, draft) · 0002 (tuner, scaffold) · 0003 (orchestrator, scaffold)
cat specs/0001-tiered-cascade-router/prd.md
```

---

## Current Status

**Active workstream: the routing/composition pillar** — the "Routing" leg of
patchwork's thesis, now a concrete architecture. (The older Phase-0 latent-bridge
/ Qwen2.5 investigations still live in `plans/index.md`; they are a separate,
paused thread.)

**Where we are:** design is deep and largely settled; **nothing is built yet.**
The router (spec 0001) is `draft`; the two control-plane specs (0002 tuner, 0003
orchestrator) are `draft` scaffolds awaiting planning.

**Master doc:** `docs/routing-architecture.md` — planes, taxonomy, certificate
rungs, evidence, decision register, DAG, glossary. Everything references it.

---

## What Was Last Built / Decided (this session)

**Architecture (settled):**
- [x] **Data plane / control plane split.** Router = fast, dumb, standalone,
      **dark-operable** data plane. Tuner (0002) + orchestrator (0003) = out-of-band
      async control plane. They act **only** through the router's **control surface**
      (hard interface — `specs/0001/control-surface.md`).
- [x] **Design tenet:** agent-operable control surfaces for underspecified problems;
      build for day-2 operability from day one. Intelligence lives in the operators
      (control plane), not frozen into the tool.
- [x] **Governance:** firm-based / hierarchical (quorum is a *separate* project).
- [x] **Cascade is the spine** (verify-and-escalate); the predictor is demoted to a
      weak class-prior (P1). Verifiers indexed by **certificate cost (rungs 0–5)**;
      organize classes by **verifiability, not topic**.

**Empirical (this session, don't re-derive — `specs/0001/results.md`):**
- [x] **P1 confirmed:** embeddings cluster by class (0.615 vs 0.457) but LOO tier
      accuracy 0.33 < 0.67 baseline — they see class, not difficulty.
- [x] **Verifier config closed:** agentic rung-0 nested-tool check (drop step-sprawl);
      reasoning rung-1 plug-back + rung-4 judge; emotional = rung-5 → **fixed policy
      (floor T1)**, not a verifier.
- [x] **λ directional:** per-class 0.40 / 0.35 / 0.20.
- [x] Harness promoted: `experiments/router/closure.py` + fixtures (reproducible).

**Docs produced this session:** `docs/routing-architecture.md`; `specs/0001`
(prd reframed to data-plane, `control-surface.md`, `design.md` verifier registry,
`decisions.md`, `results.md`, `tests.md`); `specs/0002` + `specs/0003` scaffolds.

---

## What's Next (Prioritized)

### Tier 1 — Plan the control plane (the operator's stated next step)
- [ ] **Spec the control surface** (`specs/0001/control-surface.md` → firm the
      schema). **This is the pivot** — it gates 0002 and 0003.
- [ ] **Plan 0003 orchestrator:** the *attention budget* (routing its own inspection).
- [ ] **Plan 0002 tuner:** *trust/label-provenance* on classes it can't cheaply label.

### Tier 2 — Close the router's standalone-operability gaps (spec 0001)
- [ ] Layer arbitration + who owns class detection (embedder > rules for class).
- [ ] Cascade policy (terminal-failure, retry-vs-escalate, skip-start, budget).
- [ ] Cost model (add model-swap/residency + verifier cost).
- [ ] Infra-failure handling (tier down / 27B OOM-thrash).
- [ ] Cold-start / zero-config default mode.

### Tier 3 — The foundation that unblocks the predictor (Phase 0 precursor)
- [ ] Exemplar corpus + class-taxonomy expansion → re-run closure experiments at
      n ≫ 6 → decide predictor posture. (Not yet spec'd; the DAG's root.)

---

## Open Questions / Blockers

- **Predictor posture** (difficulty feature vs prefilter/cascade-dominant) — needs
  the corpus (Tier 3) to resolve.
- Control-surface **transport** (in-process vs IPC/HTTP) and exemplar-store
  concurrency (single writer = tuner, single reader = router).
- All Tier-2 gaps above are unresolved but *don't block* planning the control plane.

## Gotchas

- **Only one model is resident at a time on the 16 GB M2.** Escalating tiers means
  *loading* a model — swap latency can dominate; the 27B (T2) **OOM-thrashes** if
  the box isn't clean. The Exp-3 cost model ignored this — fix it.
- Thinking-tier models (T2, Ornith) need ≥1000 completion tokens or they emit an
  empty answer.
- All four tested models run on **stock `mlx_lm`**; the 8B-1bit was deleted (needed
  a PrismML fork). Models are in the HF cache.
- `/no_think` does **not** work on Ornith (it reasons about the directive).
- Eval substrate lives in **spark**, not patchwork: `spark/MODEL-EVAL-2026-07-15.md`,
  `spark/bake-offs/`, `spark/spikes/human-emotion-eval-skill.md`.
