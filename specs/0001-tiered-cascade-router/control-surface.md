# Spec 0001 — Control surface (the hard interface) — v1 FIRM

> **Status: firmed 2026-07-16.** This is the schema dark-core implements and the
> contract 0002/0003 are planned against. Open questions from the earlier draft
> (transport, exemplar-store concurrency, bounds format) are **resolved** below;
> the decision records are at the end.

The router (data plane, "**dark-core**") exposes a **control surface**: the set of
parameters and state that the control plane (0002 tuner, 0003 orchestrator) may
read and actuate. It is a **hard interface** — the tuner and orchestrator act
*only* through it, and dark-core has *no* hard dependency on either. This
decoupling is the invariant that lets the router ship standalone and lets the
control-plane minds be built, replaced, or run out-of-process without touching
the data path.

See `../../docs/routing-architecture.md` §3 for the topology.

---

## 1. Transport (v1, resolved): a versioned config file + patch journal

```
experiments/router/darkcore/config.json            # THE surface (current committed config)
experiments/router/darkcore/config.journal.jsonl   # append-only patch history (attribution)
experiments/router/darkcore/exemplars/             # snapshot store (see §5)
```

- **Read** = read the file. **Write** = the `set_config` protocol (§3): validate →
  write `config.json.tmp` → atomic `rename(2)`. POSIX rename atomicity is the
  concurrency primitive; readers never see a torn config.
- Dark-core reads the config at start and **hot-reloads** on version change
  (mtime poll each `route()` entry — the read is a stat, ~µs; no watcher thread).
  In-flight requests finish on their pinned version.
- The control plane may live in another process, another runtime, or be a human
  with an editor — the surface doesn't care. `set_config` ships as both a library
  call and a CLI (`darkcore config set/patch/get`); **both go through the same
  validator**. Editing the file by hand bypasses validation and is therefore
  out-of-contract (dark-core still re-validates on load and falls back to last
  known-good on an invalid file — see §6).
- HTTP/IPC is deferred: nothing in this schema changes if a daemon later serves
  the same three operations over a socket. The file *is* the v1 socket.

## 2. Operations

```
get_config()                      -> {surface_version, config_version, params}
get_state()                       -> {config_version, live_metrics}      # read-only
set_config(patch, base_version, actor) -> ok {new_version} | conflict {current_version} | invalid {violations[]}
```

- **Versioned.** `config_version` is monotonic, bumped on every applied patch.
  `set_config` carries the `base_version` the caller edited against; stale base →
  `conflict`, no write (optimistic concurrency). Nobody blind-writes.
- **Validated.** The patch (RFC-7386-style merge patch over `params`) is applied
  to a copy, then the *whole resulting config* is checked against §4's
  invariants. Any violation → `invalid`, zero partial application.
- **Atomic hot-reload.** Valid result swaps in whole via rename; dark-core picks
  it up on a config-version boundary. No restart, no dropped requests.
- **Attributable.** Every applied patch appends one journal line:
  `{ts, actor, base_version, new_version, patch, note}`. Rollback = re-apply an
  old journal state as a new patch (versions never go backward).
- **Read/write split.** `params` are the only writable state. `live_metrics`
  (§7) are read-only, derived from telemetry.

## 3. The schema (writable `params`)

`surface_version: 1`. Concrete shape with shipped defaults:

```jsonc
{
  "surface_version": 1,
  "config_version": 0,                  // bumped by set_config; 0 = shipped defaults
  "updated": "2026-07-16T00:00:00Z",
  "updated_by": "default",              // actor of last patch: tuner|orchestrator|operator|default
  "params": {

    "tier_roster": [                    // ordered cheapest→dearest; owner: orchestrator
      { "id": "T0", "model": "prism-ml/Ternary-Bonsai-1.7B-mlx-2bit", "max_tokens": 512  },
      { "id": "T1", "model": "prism-ml/Ternary-Bonsai-8B-mlx-2bit",   "max_tokens": 768  },
      { "id": "T2", "model": "prism-ml/Ternary-Bonsai-27B-mlx-2bit",  "max_tokens": 1536 }
    ],

    "class_start_map": {                // class → starting tier; owner: tuner
      "agentic": "T0", "reasoning": "T0", "emotional": "T1", "default": "T0"
    },

    "class_floor": {                    // class → minimum tier; owner: orchestrator
      "emotional": "T1", "default": "T0"
    },

    "lambda_by_class": {                // λ in utility = quality − λ·cost; owner: tuner
      "agentic": 0.40, "reasoning": 0.35, "emotional": 0.20, "default": 0.35
    },

    "verifier_config": {                // class → {rung, verifier id, thresholds}; owner: tuner
      "agentic":   { "rung": 0, "verifier": "nested_tool_check", "thresholds": {} },
      "reasoning": { "rung": 1, "verifier": "plugback_or_judge", "thresholds": {} },
      "emotional": { "rung": 5, "verifier": null, "thresholds": {} },   // rung 5 ⇒ fixed policy, never verified
      "default":   { "rung": 4, "verifier": "next_tier_judge",  "thresholds": {} }
    },

    "prefilter_rules": [                // ordered, first-match-sets-field; owner: tuner/orchestrator
      { "id": "tool-list",  "signal": "tool_roster_present", "set": { "class": "agentic" } },
      { "id": "code-fence", "signal": "code_fence_present",  "set": { "class": "agentic" } },
      { "id": "affective",  "signal": "affective_first_person", "set": { "class": "emotional" } }
    ],

    "exemplar_store_ref": {             // owner: tuner (the single writer)
      "uri": null,                      // null ⇒ no store ⇒ predictor forced off
      "index_version": 0
    },
    "predictor_enabled": false,         // owner: tuner; AND-ed with store presence

    "cascade_policy": {                 // owner: orchestrator
      "max_tiers_per_query": 3,         // escalation budget (attempts, not roster size)
      "per_query_ms_budget": 300000,    // wall clock incl. swaps; breach → finish current tier, no further escalation
      "retry_policy": "escalate",       // escalate | retry_once_then_escalate
      "skip_start": false,              // permit jumping past the start tier on strong signal
      "terminal_failure": "emit_flagged" // T2 verifier also fails → emit + alarm (never silent)
    },

    "escalation_overrides": {}          // class → pinned tier ("emotional": "T2"); owner: orchestrator
  }
}
```

## 4. Bounds & invariants (validated on every patch AND every load)

Declared as code in one place (`surface.py`), enforced identically by the
library, the CLI, and dark-core's loader. Violation ⇒ `invalid` (patch) or
fall-back-to-last-known-good (load).

| # | Invariant |
|---|---|
| I1 | `tier_roster` non-empty; ids unique; order is cost order (cheapest first) |
| I2 | Every tier referenced anywhere (`start_map`, `floor`, `overrides`) ∈ roster |
| I3 | `class_start_map` and `class_floor` each contain `"default"` |
| I4 | `start(class) ≥ floor(class)` for every class in either map |
| I5 | `0 ≤ λ ≤ 2.0` per class |
| I6 | `verifier_config`: rung ∈ 0..5; **rung 5 ⇔ verifier null** (fixed-policy classes are never verified); named verifiers must exist in the registry |
| I7 | `prefilter_rules`: ids unique; signals from the registered signal set; rules only *set* fields, never call models |
| I8 | `exemplar_store_ref.uri` null or resolvable; `predictor_enabled=true` requires non-null uri (else auto-false at load, warn) |
| I9 | `cascade_policy`: `1 ≤ max_tiers_per_query ≤ |roster|`; `per_query_ms_budget > 0`; enums valid |
| I10 | Patch cannot change `surface_version` (that's a migration, not a patch) |

**Safe by construction:** no accepted patch can crash dark-core, breach a floor,
or violate the PII rule — the worst a bad tune can do is degrade quality.

## 5. Exemplar store (resolved): immutable snapshots, single writer

The store is the one shared *artifact* (vs. parameter) between planes:

- **Single writer: the tuner.** It builds a **new immutable snapshot**
  `exemplars/v<N>/` (embeddings + labels + manifest with content hash), then
  publishes it with one `set_config` patch bumping `exemplar_store_ref`
  `{uri, index_version}`.
- **Single reader: dark-core.** It memory-maps the snapshot named by the current
  config and reloads only on `index_version` change. It never sees a
  half-written index because snapshots are never mutated — the *ref swap* is the
  commit point, and it rides the same atomic config rename as everything else.
- Old snapshots are garbage; the tuner may keep the last K for rollback.
- Content rule inherited from D6/PII: snapshots hold **embeddings + derived
  features + labels, never raw text.**

## 6. Guarantees dark-core upholds

1. **Dark-operable.** No control plane attached ⇒ runs on last committed config,
   or shipped defaults (`config_version: 0`) if no file exists. Never blocks on
   the control plane. An unparseable/invalid config file at load ⇒ log
   `config_invalid` + run on last known-good (or defaults) — degrade, never die.
2. **Safe by construction.** §4 — bounds are enforced at the surface, not by
   caller discipline.
3. **Observable-then-actuated.** The only levers are `params`; there is no side
   channel. `live_metrics` never feed back into routing except via a patch.
4. **Attributable.** The journal reconstructs every config the router has ever
   run, who set it, and when. Telemetry records `config_version` per trace, so
   any routing decision joins back to the exact knobs that produced it.

## 7. Read-only `live_metrics` (what `get_state` serves)

Rolling counters/gauges derived from telemetry, PII-safe (hashes + features,
never content): tier distribution, escalation rate (overall + per class),
verifier verdict counts (per class × verdict), router overhead ms
(p50/p95), per-tier availability + latency + **swap count/latency**, current
`config_version`, and a sample-buffer handle (trace ids only) for the rung-5
classes — the orchestrator's volitional-inspection feed. v1 implementation:
computed on demand from the JSONL telemetry (`get_state` = a rollup over
`logs/router/`), not a resident counter service.

## 8. Who actuates what (the contract 0002/0003 are planned against)

| Knob | tuner (0002) | orchestrator (0003) |
|---|---|---|
| `lambda_by_class`, `verifier_config`, `class_start_map`, `prefilter_rules` | ✍ writes | reads |
| `exemplar_store_ref` (+ snapshots), `predictor_enabled` | ✍ **sole writer** | reads |
| `class_floor`, `cascade_policy`, `escalation_overrides`, `tier_roster` | reads | ✍ writes |
| `live_metrics`, telemetry, sample buffer | reads | reads |

Two writers, disjoint knob sets, one optimistic-concurrency journal — write
conflicts are structurally rare and detected when they happen.

## 9. Decision records (what got resolved, and why)

- **T1 — Transport = versioned file + atomic rename (not a daemon).** *Why:* the
  strongest form of dark-operability — the surface exists even when nothing is
  running; the control plane can be out-of-process (or a human) with zero new
  infrastructure; rename gives atomicity for free; and the schema is
  transport-portable if a daemon arrives later. *Revisit when:* the control
  plane needs sub-second actuation latency or remote actuation.
- **T2 — Bounds/invariants as code in one shared module, not a schema language.**
  *Why:* I4/I6/I8 are cross-field invariants that JSON Schema expresses poorly;
  one `validate(config)` function used by writer *and* loader is smaller and
  cannot drift from itself. *Revisit when:* a non-Python actuator appears.
- **T3 — Exemplar concurrency = immutable snapshots + ref swap.** *Why:* turns a
  reader/writer race into a pointer swap that reuses the config's own atomicity;
  index versions make staleness explicit; rollback is a ref change. (§5)
- **T4 — `get_state` = on-demand rollup over telemetry, not a metrics daemon.**
  *Why:* control plane is async/out-of-band by definition (§3 of the
  architecture doc) — freshness-on-read is sufficient, and it keeps dark-core to
  one process with no shared mutable state. *Revisit when:* metric queries get
  hot enough to matter.
