# Spec 0002 — Config tuner (control plane) — SCAFFOLD

> **Draft scaffold.** Captures role + decisions so far; full planning is the next
> session's job. Read `../../docs/routing-architecture.md` (§3, §5, §11) first.

## Role

The **configuration/learning** half of the control plane. Out-of-band and
**asynchronous** — never in the request path. It consumes the router's telemetry,
recomputes router parameters, and **hot-reloads** them through the router's
**control surface** (`../0001-tiered-cascade-router/control-surface.md`). It is the
"engineer adjusting the valves," slow and deliberate, cross-session.

## What it actuates (through the control surface, only)

`lambda_by_class`, `verifier_config` (rungs + thresholds), `class_start_map`,
`prefilter_rules`, and it is the **single writer of the exemplar store**
(`exemplar_store_ref`). It reads `live_metrics` + the telemetry stream.

## What it does (candidate scope)

- **Exemplar curation** (the D6 loop, relocated here): turn verified production
  traces into labeled exemplars — *gated on label trustworthiness* and the PII rule
  (features/hash, not raw text). Grows `n`, which strengthens the router's predictor.
- **Recalibration:** re-run the λ sweep / verifier thresholds on the accumulated
  corpus; firm the directional 0.40/0.35/0.20.
- **Adaptive policy (later):** the RL/bandit family (taxonomy C) lives here — learn
  λ / start-map online from cost-vs-reward feedback (handles nonstationarity, K1).

## The hard problem (why this needs its own spec)

**Trust / label provenance on classes it can't cheaply label.** The tuner learns
from telemetry, but those labels are only as good as the verifiers that produced
them. So it improves the router *well* for verifiable classes (rung 0–1) and
*poorly* for rung-5 classes (emotional, open-ended) — the certificate problem
propagates into the learning loop. How the tuner earns trust where it has no
reliable label (human-in-loop labels? accept-soft-label? refuse-to-tune?) is the
central open question. Also: within-session `n` is tiny — real learning is
cross-session off the accumulating store.

## Decisions carried in

- Firm-based/hierarchical governance; decoupled via the control surface (hard
  interface); acts only through knobs.
- Exemplar growth is a tuner function, not a router function (router only emits).

## Dependencies

- `depends_on: 0001` — specifically its **control surface**, which must be fixed
  before this can be planned (the tuner *is* defined by what it can actuate).

## Out of scope

- Supervisory/alarm duties (that's 0003, the orchestrator).
- Anything in the request path (the tuner is always out-of-band).
