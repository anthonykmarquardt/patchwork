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

## Interfaces

- `route(query) -> {answer, tier, escalations, trace}` — the one public entry.
- Tiers are served via the existing spark registry / `mlx_lm.server` endpoints
  (T0/T1/T2 already wired and benchmarked this session).
- Verifiers and the embedder are pluggable (registry pattern) so the design
  survives swapping models.

## Out of scope (restated)

Token-level routing, latent bridging, a trained router model, API-model routing,
and the memory-tiering loader (router only *selects* a resident tier).

## References

See `references/` and `references.md`. Primary: arXiv:2505.12601. Context:
Arch-Router (2506.16655), RouteLLM, routing/cascade survey (2603.04445).
