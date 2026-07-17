# Spec 0003 — Supervisory orchestrator (control plane) — SCAFFOLD

> **Draft scaffold.** Captures role + decisions so far; full planning is the next
> session's job. Read `../../docs/routing-architecture.md` (§3, §11) first.

## Role

The **supervisory** half of the control plane. **Firm-based / hierarchical** — the
smartest (most expensive) mind, sitting *above* the router, not in its request
path. It watches for trouble and intervenes via policy, but does **not** handle
individual queries. It is the senior engineer who mostly delegates, responds to
escalations, and occasionally walks the floor.

## Two supervision channels (the two halves of the certificate ladder)

- **Alarms (reactive)** — the *loud* failures, where a cheap certificate exists
  (rungs 0–4) and fires upward: verifier rejections, cascade terminal-failures (T2
  also failed), infra failures, budget breaches. The orchestrator consumes these.
- **Volitional inspection (proactive)** — the *silent* failures, rung-5 classes
  with **no certificate**, which by definition raise no alarm. The orchestrator
  must *choose* to sample and inspect these (emotional, open-ended, creative). This
  is the only safety net there, and it is inherently probabilistic.

## What it actuates (through the control surface, only)

`class_floor`, `cascade_policy` (budgets, skip-start, terminal-failure handling),
`escalation_overrides`, `tier_roster`. It reads `live_metrics` and the sample
buffer for inspection.

## The hard problem (why this needs its own spec)

**The attention budget — routing its own inspection.** If the orchestrator is the
most expensive mind and it "occasionally examines state," that examination costs
frontier inference — the exact cost tiering was meant to avoid. So its attention
must itself be **budgeted and routed**: which queries/classes to inspect, how
often, under what signal. This is the routing problem pushed up a level (recursive
routing) — a *finite* stack of turtles, but the budget policy is the crux. Also:
silent-failure coverage is only ever *sampled*, so the real design question is
"what silent-failure rate per class do we tolerate," not "catch them all."

## Decisions carried in

- Firm-based/hierarchical (not quorum — that's a separate project).
- Decoupled via the control surface (hard interface); acts only through knobs.
- Reactive (alarms) + proactive (volitional inspection) are complementary and both
  required — alarms can't cover the no-certificate classes.

## Dependencies

- `depends_on: 0001` — its **control surface** (the orchestrator is defined by what
  it can actuate) and its **alarm/telemetry** channel.

## Out of scope

- Config/learning duties (that's 0002, the tuner).
- Being in the request path (always out-of-band; overrides act via policy, not
  per-query interception).
