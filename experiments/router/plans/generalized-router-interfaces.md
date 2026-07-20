# Plan: Generalized Router Interface Boundaries

> **Status:** idea stage — no implementation scheduled. Documented 2026-07-18
> from an operator thought experiment.
> **First concrete customer (2026-07-18):** `spark/specs/0001-model-fleet-api/`
> (wip-research). Its S3/S6 spikes need an HTTP `Tier` backend and a served
> `Enricher` (embedder) behind fallback switches — when that spec exits
> research, §2's `Tier` and `Enricher` protocols are the patchwork-side work.
> **Scope:** LLM inference routing only. (The original discussion touched
> DDoS-guard / load-balancer generalization; those were illustrative of how
> common the routing pattern is, and are explicitly out of scope.)
> **Prereq reading:** `docs/routing-architecture.md` §3–4 (planes, layers),
> `specs/0001-tiered-cascade-router/`.

---

## 1. Motivation

The routing pattern — observe traffic, classify, dispatch, verify, escalate —
is general. Within dark-core today the layers (prefilter / predictor / cascade
/ observability) are conceptually separate but not abstracted as interfaces in
code: `cascade.py` imports concrete classes, and the predictor/verifier
strategies are baked in rather than pluggable.

Two payoffs from formalizing the boundaries:

1. **Portability across model architectures.** Swapping the embedder, the
   classifier strategy, or a tier's backend becomes a config/manifest change,
   not a code change. This matters near-term: the mlx port of bge-small
   (CONTINUE.md backlog item 5) is exactly an embedder swap, and the
   D4 finding (exemplars store embeddings, never text) makes embedder
   migrations expensive — a hard interface at least makes them *legible*.
2. **Single-responsibility encapsulation.** Escalation policy becomes testable
   independent of which embedder or judge is plugged in.

**Design tension to respect:** the router's value proposition is a dumb, fast,
zero-config data plane with intelligence out-of-band (arch doc §2–3).
Generalization must not push stateful or windowed analysis into the request
path. Windowed traffic observation stays a *control-plane consumer of
telemetry*, never a data-plane interface.

---

## 2. The four boundaries

### 2.1 `Enricher` (today: `predictor.py`)

```
propose(query) -> Signal
# Signal = {class?: str, tier_hint?: str, confidence: float, features: dict}
```

- Implementations: embed+kNN (current, class-prior mode), learned classifier
  head, difficulty/correctness predictor (the post-corpus P1 attack, arch doc
  §5-A).
- The cascade consumes a `Signal` and doesn't care which implementation
  produced it. `predictor.py` already only talks to the rest of the system
  through roughly this shape — **cleanest cut, lowest risk**.
- Arbitration (rules > embedder > abstain-to-default) stays *outside* the
  Enricher, in the router — it's policy over signals, not signal production.

### 2.2 `Tier`

```
generate(query, context, budget) -> Attempt
# Attempt = {text: str, tokens: int, latency_ms: float, model_id: str}
```

- T0/T1/T2 are already de facto swappable backends in `models.py`. Making the
  interface explicit turns the tier roster into pure config (already a named
  control-surface knob), so adding/removing a model architecture is a
  manifest edit.
- `budget` carries the existing judge caps / token caps so caps stay a
  cascade-level policy, not per-backend hardcoding.

### 2.3 `Verifier` (today: `verifiers.py`)

```
check(query, attempt, rung) -> Certificate
# Certificate = {verdict: pass|fail|inconclusive, cost: Cost, evidence: dict}
```

- Implementations: rung-0 rules (nesting + arg-shape), LLM-judge,
  self-consistency, future strategy-aware checks (residual seam A4).
- **Abstract this one first.** The certificate-rung logic is already
  rung-indexed — i.e. designed for multiple verifier strategies at different
  cost points. The interface just names what the design already assumes.
- `inconclusive` is a first-class verdict (v0.2 lesson: a certificate with
  nothing to certify is not a pass — inconclusive falls through to judge).

### 2.4 `Cascade` — the fixed spine

- **Not swappable.** Verify→escalate is the core mechanism the whole scheme
  lives or dies on (arch doc §5-B); it stays concrete.
- Change: takes `Enricher`, `Tier[]`, `Verifier` as constructor arguments
  instead of importing concrete classes. Escalation policy becomes testable
  with fakes — no models, consistent with the existing model-free test suite.

### 2.5 Observability — a sink, not a boundary

- Every layer keeps emitting to the same JSONL trace. No new interface.
- Windowed / cross-request analysis (traffic patterns over time) is a
  control-plane consumer of the telemetry stream — orchestrator-shaped
  (spec 0003), not router-shaped. Nothing windowed enters the data plane.

---

## 3. The open design question (resolve before writing any interface)

**Do `Enricher`/`Verifier` implementations share a uniform config schema, or
does each bring its own knob set?**

- **Uniform schema:** the control surface (arch doc §3) stays a hard, uniform
  contract; the 0002 tuner can actuate any implementation without
  special-casing. Cost: a lowest-common-denominator schema may straitjacket
  genuinely different strategies (a kNN's `k`/`λ` vs a classifier's threshold
  vs a judge's prompt/caps).
- **Per-plugin knobs:** each implementation registers its own knob manifest;
  the tuner discovers knobs at runtime. Cost: the control surface grows
  per-plugin variance — the tuner must understand each plugin to tune it, and
  the "hard interface" invariant weakens.

This is the actual decision hiding under "swappable." It determines whether
the load-bearing invariant (control plane acts *only through* uniform knobs)
survives generalization. Leaning: **a small uniform core (enable, weight,
threshold, budget) + a namespaced per-plugin extension block**, so the tuner
can do coarse actuation uniformly and fine actuation only for plugins it
knows. Needs operator sign-off before any interface is written.

---

## 4. Sequencing (if/when this leaves idea stage)

1. `Verifier` protocol — names what the rung design already assumes; smallest
   diff, immediate test-quality payoff.
2. `Enricher` protocol — ~~unblocks the mlx embedder port as a clean swap~~
   the embedder port shipped first (2026-07-18, `darkcore/embedder_mlx.py`)
   without the protocol; the boundary held anyway (predictor's `embed()` was
   the only seam touched). The protocol remains worthwhile for the *next*
   swap; the D4 corpus-reset pressure is now discharged.
3. `Tier` protocol + roster-as-manifest.
4. Cascade constructor-injection; delete concrete imports.
5. Only then: revisit the config-schema question with the tuner (0002) design
   in hand — the answer should be co-designed with the tuner's actuation
   model, not guessed ahead of it.

Non-goals: plugin discovery/entry-points machinery, dynamic loading, any
cross-request state in the data plane, non-LLM routing domains.
