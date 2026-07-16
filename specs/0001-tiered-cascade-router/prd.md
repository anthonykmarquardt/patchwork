# Spec 0001 — Tiered cascade router

## Problem

Patchwork's thesis is composition, and the first composition primitive is a
**router**: given a query, pick the cheapest local model that will actually
satisfy it, escalating only when needed. Today serving is monolithic — every
query pays 27B-class latency/RAM even when a 1.7B would do.

This session's eval battery (`spark/MODEL-EVAL-2026-07-15.md`) established the
tiers and, crucially, a failure mode that shapes the design: the small tier
(1.7B) is **confidently wrong** — fluent, well-structured, and incorrect on
anything needing judgment (R1 trap reasoning, A1 tool semantics). A pure
upfront router that mispredicts sends a confidently-wrong answer downstream
with no safety net. So the router cannot be *only* a predictor — it must be a
**cascade** that verifies and escalates.

## Tiers (local, cost = latency + RAM, not $)

| Tier | Model | Role |
|---|---|---|
| **T0** | Bonsai 1.7B ternary (~74 tok/s, 0.5 GB) | mechanical / procedural |
| **T1** | Bonsai 8B ternary (~27 tok/s, 2.3 GB) | default workhorse |
| **T2** | Bonsai 27B ternary (~6–9 tok/s, 7.9 GB) | escalation / nuance |

(Ornith-9B 4-bit is an alternate T1 "deliberate reasoner" — see MODEL-EVAL.)

## Goals (all three layers — the operator confirmed "1, 2, 3, cascade")

1. **Programmatic prefilter** — cheap deterministic heuristics that short-circuit
   obvious cases (code fence / tool-list present → agentic; affective first-person
   cues → escalate; length/format signals). Transparent, zero model calls.
2. **Embedding + kNN tier predictor** — embed the query, kNN over **labeled
   exemplars seeded from the eval battery**, predict the smallest tier likely to
   satisfy. Follows arXiv:2505.12601 (kNN ≥ learned routers): cosine, k≈50–100,
   `utility = quality − λ·latency`, add a tier by dropping in exemplars (no retrain).
3. **Cascade verify-and-escalate** (the spine) — run the predicted tier, apply a
   task-appropriate verifier; on failure, escalate to the next tier. This is what
   makes the confidently-wrong T0 safe.

## Out of scope

- Token-level / per-phrase routing and latent bridging ("telepathy") — separate
  patchwork specs.
- Training a bespoke router *model* (Arch-Router-style). kNN is deliberately
  training-free.
- Multi-node / distributed serving; API-model routing (RouteLLM territory).
- The memory-tiering/cold-swap loader (assumed available; router only *selects*).

## Success criteria

- **Quality retention:** on a held-out slice of the battery, cascade output quality
  ≥ (T2-only − ε) while routing ≥ 60% of queries to T0/T1.
- **Safety:** the confidently-wrong fixture (a T0 R1-style trap) is **caught by the
  verifier and escalated**, not emitted.
- **Extensibility:** adding a tier is exemplars-only — no retrain, no code change to
  the predictor.
- **Budget:** router overhead (prefilter + embed + kNN) < 20 ms/query on the M2.
- **Reproducibility:** `verify.py` regenerates the cost/quality report from the
  labeled battery deterministically.

## Task checklist

- [ ] Assemble `battery.jsonl` — the R1/R2/A1/A2/E1/E2 prompts + per-tier
      pass/fail labels from this session's runs, as the exemplar/label set.
- [ ] Layer 1: `prefilter.py` — deterministic rule set returning
      `{route_hint | None, reason}`; unit-tested, side-effect free.
- [ ] Layer 2: `predictor.py` — embed (pluggable; default `bge-small`), hnswlib/FAISS
      kNN index over exemplars, `utility = quality − λ·latency` → predicted tier.
- [ ] Layer 3: `cascade.py` — run tier → verifier → escalate; pluggable per-class
      verifiers (schema/return-check for agentic, self-consistency for reasoning,
      an engagement check for emotional).
- [ ] `router.py` — wire prefilter → predictor → cascade behind one `route(query)`.
- [ ] Verifiers registry — minimum set per §tests, task-class dispatch.
- [ ] `verify.py` harness — run battery through the router, emit `report.json`
      (per-query tier, escalations, quality, latency) + assert thresholds.
- [ ] Wire the served tiers to existing endpoints (spark registry / `mlx_lm.server`).
- [ ] Tune λ and the kNN k on the validation slice; record chosen values.
- [ ] Flip `status.yaml` `state: draft → ready` once design questions below close.

## Open design questions (resolve before `ready`)

- Embedder choice/latency on M2 (bge-small vs gte-small vs Qwen3-Embedding-0.6B).
- Verifier strength per class — how cheap can the escalation trigger be while still
  catching confidently-wrong T0?
- λ default and whether it's per-task-class.
