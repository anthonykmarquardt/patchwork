# Spec 0001 — Control surface (the hard interface)

The router (data plane) exposes a **control surface**: the set of parameters and
state that the control plane (0002 tuner, 0003 orchestrator) may read and actuate.
It is a **hard interface** — the tuner and orchestrator act *only* through it, and
the router has *no* hard dependency on either. This decoupling is the invariant
that lets the router ship standalone and lets the control-plane minds be built,
replaced, or run out-of-process without touching the data path.

See `../../docs/routing-architecture.md` §3 for the topology.

## Interface shape

Three operations, transport-agnostic (in-process call, IPC, or HTTP):

```
get_config()            -> {version, params}        # current knobs
get_state()             -> {version, live_metrics}  # read-only observed state
set_config(patch, base_version) -> {ok|conflict|invalid, new_version}
```

- **Versioned.** Every config carries a monotonic `version`. `set_config` takes
  the `base_version` it edited; a stale base → `conflict` (optimistic
  concurrency). The tuner and orchestrator never blind-write.
- **Validated.** `set_config` validates the patch against declared **bounds and
  invariants** before applying; a violating patch → `invalid`, no partial apply.
- **Atomic hot-reload.** A valid patch swaps in as a whole, on a config-version
  boundary; in-flight requests finish on their pinned version. No restart, no
  dropped requests.
- **Read/write split.** `params` are writable knobs; `live_metrics` are read-only
  (the orchestrator reads them to decide, but changes behavior only via `params`).

## The knobs (writable `params`)

| Knob | Type | Bounds / invariant | Owner (typical) |
|---|---|---|---|
| `tier_roster` | ordered list of tier ids (T0<T1<T2) | ≥1 tier; ordered by cost; must resolve to a served endpoint | orchestrator |
| `class_start_map` | class → starting tier | tier ∈ roster | tuner |
| `class_floor` | class → minimum tier | floor ∈ roster; `start ≥ floor` | orchestrator |
| `lambda_by_class` | class → λ | λ ∈ [0, λ_max] | tuner |
| `verifier_config` | class → {rung, thresholds} | rung ∈ 0..5; thresholds in declared ranges | tuner |
| `prefilter_rules` | ordered rule table | each rule well-formed; deterministic | tuner/orchestrator |
| `exemplar_store_ref` | pointer/uri + index version | resolvable; predictor may be disabled if empty | tuner |
| `cascade_policy` | {max_tiers, per_query_ms_budget, retry_policy, skip_start} | budget > 0; max_tiers ≤ \|roster\| | orchestrator |
| `predictor_enabled` | bool | — (auto-off when exemplar store empty) | tuner |
| `escalation_overrides` | optional per-class/pinned-route policy | must resolve to roster tiers | orchestrator |

## Read-only `live_metrics` (state the orchestrator inspects)

Rolling counters/gauges derived from telemetry: tier distribution, escalation rate
(overall + per class), verifier false-accept/false-escalate estimates, router
overhead ms, per-tier availability/latency, current config version, and a sample
buffer handle for the no-certificate classes (for volitional inspection). **No raw
query/response content** (PII rule) — hashes and derived features only.

## Guarantees the router must uphold

1. **Dark-operable.** With no control plane attached, the router runs on its last
   committed config (or shipped defaults). It never blocks on the control plane.
2. **Safe by construction.** No `set_config` can drive the router outside declared
   bounds; the worst a bad tune can do is degrade quality, never crash or breach a
   floor/PII invariant.
3. **Observable-then-actuated.** The orchestrator's only levers are `params`;
   there is no side channel that bypasses the surface.
4. **Attributable.** Every applied patch is logged (who/when/base→new version) so
   the tuner/orchestrator can be audited and rolled back.

## Why this is the pivot

0002 (tuner) and 0003 (orchestrator) are **defined by what they can actuate
through this surface** — the tuner writes `lambda_by_class`, `verifier_config`,
`class_start_map`, `exemplar_store_ref`; the orchestrator writes `class_floor`,
`cascade_policy`, `escalation_overrides` and reads `live_metrics`. So this
interface must be fixed **before** those specs can be planned. It is the first
thing to build in 0001 after the dark core.

## Open questions

- Transport for v1 (in-process is simplest; IPC/HTTP if the control plane runs
  out-of-process — likely, for isolation).
- Exemplar-store write path: the router **reads** the store; who **writes** it is
  the tuner (see routing-architecture §5), so the store is a shared artifact with
  a single writer (tuner) and single reader (router) — confirm the concurrency
  model.
- Bounds/invariant declaration format (schema) — pydantic-style, shared with the
  registry.
