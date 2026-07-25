# Plan: Concierge → Specialist Routing Mode

> **Status:** idea stage — no implementation scheduled. Documented 2026-07-24.
> **Triggered by:** MiniCPM5-1B-8bit benchmark showing asymmetric competence
> (T1 emotional, T0 reasoning, T0-incompetent agentic). A single ladder cannot
> express a model that is simultaneously the best and worst choice depending
> on role.
> **Relationship to banter:** This is the "multi-model consortium" vision from
> `banter/docs/foundation/03-architecture-principles.md` §3, distilled to a
> concrete data-plane extension.
> **Prereq reading:** `docs/routing-architecture.md` §3–4,
> `experiments/router/plans/generalized-router-interfaces.md` §2,
> `experiments/minicpm5-results.json`.

---

## 1. Motivation

The current router has one tier roster and one class→start/floor map:

```python
"tier_roster": [
    {"id": "T0", "model": "Bonsai-1.7B"},
    {"id": "T1", "model": "Bonsai-8B"},
    {"id": "T2", "model": "Bonsai-27B"},
],
"class_start_map": {"agentic": "T0", "reasoning": "T0", "emotional": "T1"},
```

The MiniCPM5 benchmark falsified the implied monotonicity assumption — its
competence profile is not a scalar:

| Role | MiniCPM5 1B | Bonsai 1.7B | Bonsai 8B | Bonsai 27B |
|------|:----------:|:----------:|:---------:|:----------:|
| Emotional | ~T1 (0.72) | T0 (0.33) | T1 (0.78) | T2 (0.98) |
| Reasoning | ~T0 (0.52) | ~T0 (0.55) | T1 (0.93) | T2 (1.00) |
| Agentic | ~T0-incompetent (0.15) | T0 (0.28) | T1 (0.73) | T2 (1.00) |
| Chat/general | ~T1 (0.80) | ~T0 (0.50) | T1 (0.85) | T2 (1.00) |

MiniCPM5 is simultaneously **the best emotional model under T2** and
**the worst agentic model in the pool** — a split no single ladder captures.

Two design responses:

**A. Per-class tier rosters** (straightforward extension).
Each role column picks its own lightweight/heavy hierarchy. The router
classifies, then runs that column's cascade. MiniCPM5 participates in the
emotional column. Minimal change to the existing architecture.

**B. Concierge → Specialist** (the architectural proposal below).
A front-layer model (the concierge, MiniCPM5) intercepts every query. It
handles what it can directly and **generates a handoff summary** for what
it can't, then the role-specific cascade runs with that summary as context.
The user gets a warm response from the concierge (0.2s TTFT) while the
specialist model loads.

---

## 2. The concierge layer

### 2.1 What it is

A new first layer in the data plane, between prefilter and the per-role
cascade:

```
Current:   query → prefilter → predictor(class) → cascade(role)
                                                    ↑ per-role tiers

Concierge: query → prefilter → predictor(class) → concierge → cascade(role)
                                                     │
                                                     ├─ serve directly (role=chat/general/emotional)
                                                     └─ handoff(role, summary) → cascade(role)
```

The concierge is a **fast, warm, always-resident model** that serves as the
system's voice for every query. For queries within its competence, the answer
is delivered immediately. For queries beyond its tier, it produces a
**handoff summary** — a compressed description of the user's intent,
emotional state, and what the specialist needs to answer — then the
specialist cascade runs with that summary.

The user sees:
```
[immediate] "I hear you — let me think about that more carefully."
[~background] <specialist answer appears when ready>
```

### 2.2 Config shape

```python
# Proposed addition to the control surface
"concierge": {
    "enabled": False,                  # mode flag: off → current behavior
    "model": "mlx-community/MiniCPM5-1B-8bit",
    "max_tokens": 256,                 # short — concierge is fast
    "handoff_roles": ["agentic", "reasoning"],   # roles that always escalate
    "serve_roles": ["emotional", "chat", "default"],  # roles concierge owns
    "handoff_template": "The user said: {query}. Context: {class}, {summary}",
}
```

`enabled: False` means the router behaves exactly as it does today — zero
change to the existing data path. The flag is the on/off switch for the
concierge mode.

When `enabled: True` the routing flow becomes:

1. **Prefilter + Predictor** (unchanged) — class detection as today
2. **Concierge dispatch:**
   - If class ∈ `serve_roles` → MiniCPM5 generates the answer directly;
     response is final. Done.
   - If class ∈ `handoff_roles` → MiniCPM5 generates a **short handoff
     summary** (compressed intent + emotional state + open questions).
     MiniCPM5's answer is NOT served to the user (or served as a
     preliminary acknowledgment).
3. **Per-role cascade** (unchanged) — the cascade runs against the specialist
   tiers for that class, but receives the handoff summary as additional
   context in the messages array (seam-1 contract).

### 2.3 Handoff summary content

MiniCPM5 produces a short structured text before the cascade runs:

```
User is asking about an OAuth 401 issue affecting 2% of users on one AZ
after a rolling deploy. Emotional state: frustrated, urgent. They need
ordered diagnostic tool calls before rolling back. Requires agentic
reasoning with tool-call syntax.
```

This is NOT a separate model call — it's the concierge's generation for
a handoff-class query. The same generation produces the acknowledgment to
the user and the summary for the specialist.

### 2.4 Co-residency

MiniCPM5 at 1.07 GB (8-bit) fits alongside the existing T0+T1 co-resident
pair (0.46 + 2.2 = 2.66 GB → becomes 1.07 + 0.46 + 2.2 = 3.73 GB). Still
well within 16 GB. Only T2 (8.1 GB) needs exclusive residency.

The concierge is **always warm** — never evicted, always ready. This is
justified by its small footprint and the fact that it's the system's voice.

---

## 3. Two open design questions (undecided)

### 3.1 Mode vs always-on

Should concierge→specialist be a **config switch** (`concierge.enabled`) as
proposed above, or the **default routing mode** with the current flat-cascade
behavior as a legacy compatibility mode?

- **Config-switch case:** The current cascade works and is proven (BENCH-REPORT
  v0.2, all thresholds pass). Adding a new mode alongside it lets us bench
  both and compare empirically. The switch is a single boolean — cheap to
  carry.
- **Always-on case:** If MiniCPM5 replaces Bonsai 1.7B as the default T0 in
  the emotional column, and the concierge is just per-class roster extension
  without the handoff semantics, there's no "mode" at all — just a richer
  tier roster.

**Current leaning:** config-switch. The handoff summary generation is the
novel part, and it needs empirical validation — does MiniCPM5's short
summary actually help the specialist produce a better answer than the raw
query alone?

### 3.2 Concierge decides vs class decides

Who decides whether a query gets served or handed off?

- **Class-based** (proposed above, simplest): if the query's detected class
  is in `handoff_roles`, hand off; otherwise serve. Deterministic, testable,
  no extra model call.
- **Concierge self-assessment:** ask MiniCPM5 for a confidence score or
  explicit "can you handle this?" signal. More adaptive (a simple emotional
  query might stay, a complex one might escalate) but adds latency and a
  callout-evaluation step.
- **Hybrid:** class decides the default; the concierge can override if its
  confidence is very high/low on a specific generation.

**Current leaning:** class-based for v0. The bge-small classifier already
runs (12/12 accuracy), so the decision costs zero extra inference. The
self-assessment path is interesting but speculative — it needs evidence
that MiniCPM5's self-confidence correlates with answer quality.

---

## 4. What already exists (implemented in dark-core)

| Component | Status | Maps to concierge need |
|-----------|--------|----------------------|
| `prefilter.py` | ✓ | Role signal (tool_roster_present → agentic) |
| `predictor.py` | ✓ | Class detection (bge-small, 12/12) |
| `cascade.py` | ✓ | Per-role verify-and-escalate |
| `verifiers.py` | ✓ | Per-class verification by rung |
| `models.py` (ModelPool) | ✓ | Load/evict, co-residency policy |
| Control surface | ✓ | Knobs for enabling the mode |
| Telemetry | ✓ | Trace every route decision |
| `surface.py` tier_roster | ✓ | (needs extension to per-class) |
| Router server | ✓ | OpenAI-compatible endpoint |

## 5. What would need to change

Minimal diff. The proposed changes:

1. **`surface.py`** — add `concierge` block to config schema (I9 extended).
   Allow `tier_roster` to be either a flat list (current) or a
   `{class: [tiers]}` dict (new). Legacy mode reads the flat list.

2. **`cascade.py`** or a new `concierge.py` — implement the dispatch logic:
   if concierge enabled, run MiniCPM5, check class against handoff_roles,
   either return answer or inject handoff summary into the cascade context.

3. **`models.py` (ModelPool)** — add `always_warm` set so the concierge
   model isn't evicted by T2's exclusive load. Currently, T2 evicts
   everything (`self._evict(other, f"exclusive_load_{tier_id}")`) —
   the concierge model would need a guard.

4. **`surface.py` validate** — ensure `serve_roles` and `handoff_roles`
   partition the class set, the concierge model is in cache, and the
   concierge tier fits within the co-resident budget.

5. **`telemetry.py`** — new event type `concierge_handoff` recording the
   handoff class, summary length, and whether the concierge's answer was
   served or deferred.

**Total new code:** ~100–150 lines. No new deps. No new endpoints.
Backward-compatible via `concierge.enabled: False`.

---

## 6. Why not build this now

The current cascade (class prediction + per-class start/floor + verify-and-
escalate) works — v0.2 bench: 1.90× speedup vs T2-only, 83% ≤ T1, all five
thresholds passing. Adding concierge semantics is a second-order improvement
on top of a working system.

The MiniCPM5 benchmark shows the *need* for per-class tier rosters (option A
above), which is a simpler, more incremental change than the full concierge
handoff (option B). The natural sequence:

1. **Per-class tier rosters** — extend `tier_roster` from flat list to
   `{class: [tiers]}` dict. MiniCPM5 replaces Bonsai 1.7B in the emotional
   column. This alone fixes the asymmetric competence problem. Estimated
   diff: ~30 lines in `surface.py` + `cascade.py`.

2. **Only then: concierge handoff** — add the `__front__` layer and
   `concierge.enabled` flag. This is the larger diff above (~100–150 lines)
   and needs its own empirical validation (does handoff help specialist
   quality enough to justify the extra latency?).

**This document records option B so the design space is visible, but
recommends option A as the immediate next step if MiniCPM5 integration
proceeds.**

---

## 7. Relationship to banter

The banter project (sibling repo, `anthony-mqdt-labs/banter`) envisions a
multi-model consortium where a conversation is served by multiple
specialized models with a coherent voice. Its architecture document
(`docs/foundation/03-architecture-principles.md`) defines the layers and
the `invisible hot-swap` requirement. However, it does not specify the
data-flow mechanics of handoff — how the front model decides, what the
summary looks like, and how the specialist consumes it.

This plan is the concrete data-plane answer to banter's architectural
question. If/when banter's orchestration layer (Rust supervisor + worker
pool) is built, the concierge→specialist data flow can be adapted to its
IPC contract. The core logic — class-based dispatch, handoff summary
generation, per-role cascade — is independent of the runtime layer.

The reverse: dark-core is a working implementation of the data plane
that banter's orchestration layer would control. Running the concierge
mode in dark-core first validates the data-flow design before it gets
ported into banter's Rust spine.
