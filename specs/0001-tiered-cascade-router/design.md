# Spec 0001 — Design: tiered cascade router

## Shape

```
query
  │
  ▼
┌─────────────────┐  hint (or none)
│ 1. prefilter    │──────────────┐
│    (rules)      │              │
└─────────────────┘              ▼
  │ none                  ┌──────────────┐
  ▼                       │ 2. predictor │  predicted tier T0/T1/T2
┌─────────────────┐  emb  │  embed+kNN   │──────────────┐
│ embed(query)    │──────▶│  over battery│              │
└─────────────────┘       └──────────────┘              ▼
                                                 ┌──────────────────┐
                                                 │ 3. cascade       │
                                                 │  run tier →      │
                                                 │  verify →        │
                                                 │  escalate if fail│
                                                 └──────────────────┘
                                                          │
                                                          ▼
                                                    answer + trace
```

The three layers are independent and each is individually testable. The prefilter
can force a tier (or a floor) and short-circuit; otherwise the predictor proposes a
starting tier; the cascade is always the outer loop that guarantees quality.

## 1. Programmatic prefilter (`prefilter.py`)

Deterministic, no model call. Returns `{route_hint, floor, reason}`.
- **Structural signals:** fenced code / diffs, an explicit tool list, JSON-schema
  request → agentic class (start ≥ T1, verify with a return-check).
- **Affective first-person cues** ("I feel", "I just need", grief/relationship
  lexicon) → emotional class (floor T1, prefer T2 for high-stakes).
- **Trivial-shape** (very short, single factual/format ask) → allow T0 start.
- Anything ambiguous → `route_hint = None`, defer to the predictor.
Rules are data (a small table), unit-tested for determinism; never the final gate.

## 2. Embedding + kNN tier predictor (`predictor.py`)

Grounded in **arXiv:2505.12601, "Rethinking Predictive Modeling for LLM Routing:
When Simple kNN Beats Complex Learned Routers"** (PDF in `references/`). Findings we
rely on: routing benchmarks have strong locality (r ≈ −0.8) and low intrinsic
dimension (~2–28), so kNN over standard embeddings matches/beats MF/BERT/MLP/graph
routers, and needs no bespoke training.

Recipe:
- **Embed** with a pluggable small model (default `bge-small-en-v1.5`, L2-normalized;
  the paper shows plain BERT-768 suffices — no specialized embedder needed).
- **Index:** hnswlib (or FAISS) over the battery exemplars; cosine similarity.
- **k ≈ 50–100** (paper: k=100 > k=10).
- **Utility:** per candidate tier `m`, `ŝ(x,m) = mean_k quality(neighbor,m)`,
  `ĉ(x,m) = mean_k latency(neighbor,m)`; route to `argmax_m (ŝ − λ·ĉ)`.
  λ is the quality/latency knob (validated; possibly per-class).
- **Add a tier** = add its exemplars to the index. No retrain, no code change.

Exemplars/labels come from this session's battery (R1/R2/A1/A2/E1/E2 × per-tier
pass/fail), stored in `battery.jsonl`. This is the direct tie-in: the eval work *is*
the router's seed training set.

## 3. Cascade verify-and-escalate (`cascade.py`)

The spine, and the reason a pure predictor is insufficient — T0 is **confidently
wrong**, so we never trust a single tier's output blindly.

- Run the predicted (or prefilter-forced) tier.
- Apply the **class verifier**:
  - *agentic* — schema/return-shape + tool-call well-formedness (T0 emitted
    `run_shell("http_get(...)")`; a semantics check catches it).
  - *reasoning* — self-consistency / a cheap check of the stated result (e.g. plug
    the numbers back; R2 is verifiable, R1 needs a consistency judge).
  - *emotional* — a lightweight "did it engage the specific cue vs emit a generic
    listicle" judge (can itself be T1).
- **Pass →** return. **Fail →** escalate to the next tier and re-verify. T2 is the
  terminal tier (accept its output).
- Record the full trace (tiers tried, verifier verdicts, final tier) for the report.

Cascades are FrugalGPT-lineage; the novelty here is pairing the cascade with the
kNN predictor so most queries *start* at the right tier and the cascade only pays
for escalation on the minority that need it.

### Verifier registry — indexed by certificate rung

The verifier for each class is chosen by **certificate cost** — the cheapest check
that *reliably* catches that class's failure, subject to `certificate cost ≪ the
escalation it gates`. The full rung taxonomy (0 structural → 5 no-cheap-certificate)
and its design rules live in `../../docs/routing-architecture.md` §6–7. The
**class → rung** assignment for this spec, validated against real outputs in
`results.md` (Exp 2):

| Class | Rung | Verifier | Empirical note |
|---|---|---|---|
| agentic | **0** | tool-call/schema well-formedness (nested-tool check) | catches T0/A1 broken calls; **drop step-sprawl** (false-positives T1) |
| reasoning (checkable) | **1** | plug-back / execute (R2: 18/6 verified) | true certificate — cheap + reliable |
| reasoning (non-checkable) | **4** | verdict-only next-tier judge (R1) | caught T0/R1 confidently-wrong |
| emotional | **5 → fixed policy** | *no reliable cheap certificate* (rung-3 heuristic is soft — missed T0/E1 prose) | **don't verify — floor at T1 (D5)** |
| world-fact | 1 | ground-truth / retrieval lookup | future class |
| code-gen | 1 | run tests / typecheck | future class |
| open investigation / creative | 5 → fixed policy | none | conservative fixed tier |

**Escalation policy (open — see prd.md):** terminal-failure (T2 verifier also
fails → emit-flagged + raise an alarm), retry-vs-escalate, optional skip-start,
and a per-query escalation budget are cascade-policy knobs on the control surface.

**Layer arbitration (open):** Exp 1 shows the *embedder* separates **class** well
(0.615 vs 0.457) while prefilter rules are brittle — so **class detection likely
belongs to the predictor, not the prefilter**, with the prefilter consuming the
class to set floors. Precedence (prefilter-floor ≥ predictor-prior; cascade always
outer) and multi-label handling (P-class) are to be pinned before `ready`.

## 4. Observability (`trace.py` + telemetry) — cross-cutting

The router is a decision engine; if the decisions are opaque we cannot judge
success, debug a misroute, tune the verifiers/λ, or grow the exemplar set. So
observability is designed in, not bolted on. It must satisfy the repo's mandatory
**Runtime Logging** standard (JSONL, `ts/level/component/event/session_id/pid` +
event-specific fields) and the **PII rule** (never log raw query content).

**What every routed query emits — a decision trace:**
```
route_id, ts, session_id, class,
prefilter:   { hint, floor, reason }
predictor:   { embedder, k, neighbors:[{id,dist,tier}], utility_by_tier, lambda, predicted_tier }
cascade:     [ { tier, gen_ms, tokens, verifier, verdict, score, reason }, ... ]   # one per attempt
outcome:     { final_tier, escalations, total_ms, router_overhead_ms }
```
Returned inline on `route()` (the `trace` field) **and** persisted to
`logs/router/<YYYY-MM-DD>.jsonl`.

**Event classes** (each a JSONL line): `routing_decision` (prefilter+predictor),
`tier_dispatched`, `verifier_result`, `escalation`, `route_completed`.

**PII discipline (hard rule).** Emotional queries carry sensitive disclosures.
Logs store a **query hash + derived features** (length, class, detected cues,
listicle-ratio of the *response*) — never the raw prompt or completion. Debugging
qualitative failures without content is harder (a known tension — see
decisions.md), so the trace keeps rich *structured* signal to compensate.

**Aggregate report (`report.json`)** rolls the JSONL up into the numbers that
define success: tier distribution, escalation rate (overall + per class),
per-stage latency, per-class quality, verifier false-accept / false-escalate
rates, and **cost saved vs T2-only**. `router inspect <route_id>` renders a single
trace for debugging.

**Two second-order payoffs, by design:**
- *Tuning substrate.* The λ sweep and per-class verifier thresholds are read off
  this data — you cannot close those design questions without it.
- *Exemplar growth.* A verified production trace is a labeled datapoint
  `(query-features → tier that satisfied it)`. Appended to the exemplar store
  (features/hash only, per the PII rule), it densifies the kNN index over time —
  the router improves with traffic. This directly mitigates the cold-start failure
  mode in decisions.md.

## Interfaces

- `route(query) -> {answer, tier, escalations, trace}` — the one public entry.
- Tiers are served via the existing spark registry / `mlx_lm.server` endpoints
  (T0/T1/T2 already wired and benchmarked this session).
- Verifiers and the embedder are pluggable (registry pattern) so the design
  survives swapping models.

## Out of scope (restated)

Token-level routing, latent bridging, a trained router model, API-model routing,
and the memory-tiering loader (router only *selects* a resident tier).

## Decisions & known failure modes

The rationale behind each choice above, and an honest catalog of **where this
design is expected to break**, live in [`decisions.md`](decisions.md). Read it
before proposing a redesign — the seams are documented on purpose.

## References

See `references/` and `references.md`. Primary: arXiv:2505.12601. Context:
Arch-Router (2506.16655), RouteLLM, routing/cascade survey (2603.04445).
