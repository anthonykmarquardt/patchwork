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

A router we cannot *see into* is a router we cannot trust, debug, or improve.
Observability is therefore a first-class engineering requirement of this spec,
not an afterthought (§Goals.4).

## Tiers (local, cost = latency + RAM, not $)

| Tier | Model | Role |
|---|---|---|
| **T0** | Bonsai 1.7B ternary (~74 tok/s, 0.5 GB) | mechanical / procedural |
| **T1** | Bonsai 8B ternary (~27 tok/s, 2.3 GB) | default workhorse |
| **T2** | Bonsai 27B ternary (~6–9 tok/s, 7.9 GB) | escalation / nuance |

(Ornith-9B 4-bit is an alternate T1 "deliberate reasoner" — see MODEL-EVAL.)

## Goals

The operator confirmed all three routing layers ("1, 2, 3, cascade") plus
observability as a cross-cutting fourth requirement.

1. **Programmatic prefilter** — cheap deterministic heuristics that short-circuit
   obvious cases (code fence / tool-list present → agentic; affective first-person
   cues → emotional floor; length/format signals). Transparent, zero model calls.
2. **Embedding + kNN tier predictor** — embed the query, kNN over **labeled
   exemplars seeded from the eval battery**, predict the smallest tier likely to
   satisfy. Follows arXiv:2505.12601 (kNN ≥ learned routers): cosine, k≈50–100,
   `utility = quality − λ·latency`, add a tier by dropping in exemplars (no retrain).
3. **Cascade verify-and-escalate** (the spine) — run the predicted tier, apply a
   task-appropriate verifier; on failure, escalate to the next tier. This is what
   makes the confidently-wrong T0 safe.
4. **Observability (cross-cutting)** — every routing decision, verifier verdict,
   escalation, and latency is captured as structured, queryable evidence. It must
   be possible to answer, *from the logs alone*: which tier handled a query and
   why, whether a verifier fired and what it decided, how many tiers were tried,
   where time went, and — in aggregate — the tier distribution, escalation rate,
   per-class quality, and cost saved vs T2-only. This is the substrate for
   success measurement, debugging, the empirical tuning below, **and** the
   exemplar-growth loop (verified production traces become new kNN exemplars).
   Must comply with the repo's mandatory Runtime Logging standard (JSONL, required
   fields) and its PII rule (**log query hash + derived features, never raw query
   content** — emotional queries carry sensitive disclosures).

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
- **Observability:** every `route()` call emits a complete decision trace and the
  aggregate report reconstructs tier distribution, escalation rate, per-stage
  latency, and per-class quality — with **zero raw query content** in any log
  (PII check passes). If a metric needed to judge success can't be produced from
  the logs, observability is incomplete.
- **Reproducibility:** `verify.py` regenerates the cost/quality report from the
  labeled battery deterministically.

## Task checklist

- [ ] Assemble `battery.jsonl` — the R1/R2/A1/A2/E1/E2 prompts + per-tier
      pass/fail labels from this session's runs, as the exemplar/label set.
- [ ] Layer 1: `prefilter.py` — deterministic rule set returning
      `{route_hint, floor, class, reason}`; unit-tested, side-effect free.
- [ ] Layer 2: `predictor.py` — embed (pluggable; default `bge-small-en-v1.5`,
      L2-normalized), hnswlib/FAISS kNN index over exemplars,
      `utility = quality − λ·latency` → predicted tier.
- [ ] Layer 3: `cascade.py` — run tier → verifier → escalate; pluggable per-class
      verifiers (structural for agentic, checker/judge for reasoning, heuristic
      for emotional — see design.md §3 and decisions.md D3).
- [ ] Observability: `trace.py` + `telemetry` — structured JSONL per the repo
      Runtime Logging standard; per-request trace object; **hash-not-content**
      redaction; event classes `routing_decision / tier_dispatched /
      verifier_result / escalation / route_completed`.
- [ ] `router.py` — wire prefilter → predictor → cascade behind one `route(query)`
      returning `{answer, tier, escalations, trace}`, emitting telemetry throughout.
- [ ] Verifiers registry — minimum set per tests.md, task-class dispatch.
- [ ] `verify.py` harness — run battery through the router, emit `report.json`
      (per-query trace rollups) + assert thresholds; a `router inspect` view over
      the JSONL for single-request debugging.
- [ ] Exemplar-growth loop: verified production traces → appended to the exemplar
      store (guarded by the PII rule — store features/hash, not raw text).
- [ ] Wire the served tiers to existing endpoints (spark registry / `mlx_lm.server`).
- [ ] Empirical closure (see decisions.md): validate embedder via V2; tune per-class
      verifiers against this session's known T0 failure outputs; run the λ sweep and
      record chosen per-class λ.
- [ ] Flip `status.yaml` `state: draft → ready` once the empirical-closure step
      above is done and design.md §Open items are settled.

## Resolved design decisions (approach fixed; empirical closure pending)

Recorded in full in **`decisions.md`** (with rationale and expected failure modes).

- **Embedder → `bge-small-en-v1.5`** (default, pluggable). The paper shows small
  embedders suffice for routing; the 27B memory-edge makes a 0.6B resident embedder
  costly; the embedder's real job is coarse *class* separation, which it does well.
  *Empirical closure:* validate held-out prediction accuracy (V2) before locking.
- **Verifiers → matched to each class's failure type.** Agentic = cheap structural
  (tool-call well-formedness catches the observed broken calls); reasoning =
  ground-truth checker when checkable, else a verdict-only next-tier judge;
  emotional = cheap heuristics (listicle-ratio, interrogation count) **plus** a
  prefilter floor at T1 so the verifier faces the subtler T1→T2 call, not gross
  T0 failures. *Empirical closure:* tune each against the known T0 failure outputs.
- **λ → per-class, from one principle:** `λ_class inversely tracks verifier
  reliability` — strong/cheap verifier (agentic, checkable-reasoning) ⇒ aggressive
  (high λ, lean on the cascade); weak verifier (emotional) ⇒ conservative (low λ).
  *Empirical closure:* sweep λ on validation, pick each class at its Pareto knee
  subject to the quality floor; record values in `report.json`.

## Open items (settle before `ready`)

- Embedder validation result (V2) — confirm bge-small clears the baseline.
- Final per-class verifier thresholds (from tuning against failure outputs).
- Chosen per-class λ (from the sweep).
