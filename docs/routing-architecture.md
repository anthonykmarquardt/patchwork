# Patchwork Routing Architecture

> **Master conceptual reference for the routing/composition workstream.** Specs
> (`specs/0001`–`0003`) implement pieces of this; read this first for the *why*.
> Status: living design doc, 2026-07-16.

---

## 1. Vision

The north star is an **ecosystem of agents** — small, specialized minds composed
into something larger, with intelligence spread across a *society* rather than
baked into one monolith. The routing workstream is the first concrete step:
delegate each query to the cheapest capable model, and put the intelligence in
the **supervision and tuning around** the delegation, not in a perfect upfront
guess.

(`quorum` is a *separate* project exploring threshold/consensus governance. This
workstream is deliberately **firm-based / hierarchical** — an orchestrator
supervises subordinate workers. Don't conflate them.)

## 2. Design tenet — agent-operable control surfaces for underspecified problems

Where a subsystem targets a problem with **no closed-form solution** (difficulty
estimation, quality assessment), do **not** bake in a fixed policy. Instead:

1. Expose the subsystem's decision parameters as a **runtime-tunable,
   machine-actuatable control surface.**
2. Delegate the tuning to an **intelligent operator (LLM agent)** in the control
   plane.
3. **Design for day-2 operability and live intervention from day one** — ship the
   tool with the valves exposed and instrumented.

The intelligence is the *operator at the controls*, not logic frozen into the
tool. (Steam-engine framing: the router is the engine with exposed valves and
gauges; tuner and orchestrator are engineers at the controls.)

## 3. Topology — data plane vs. control plane

```
                 ┌─────────────────── CONTROL PLANE (out-of-band, async) ──────────────────┐
                 │                                                                          │
                 │   ┌────────────────────┐              ┌──────────────────────────────┐  │
                 │   │ 0002 CONFIG-TUNER   │              │ 0003 SUPERVISORY-ORCHESTRATOR│  │
                 │   │ config/learning     │              │ firm-based supervisor        │  │
                 │   │ recompute params    │              │ alarms + volitional inspect. │  │
                 │   └─────────┬──────────┘              └──────────────┬───────────────┘  │
                 └─────────────┼──────────────────────────────────────┼───────────────────┘
                    actuate via│  CONTROL SURFACE  (hard interface)    │actuate via
                    read state /│  knobs: maps, λ, thresholds, rules,   │read state /
                    write config│  floors, tier roster, exemplar ptr    │policy override
                 ┌─────────────▼──────────────────────────────────────▼───────────────────┐
                 │                          DATA PLANE                                      │
                 │   0001 ROUTER   (standalone, zero-config, dark-operable)                 │
                 │   query → prefilter → [predictor] → cascade(verify+escalate) → answer    │
                 │                         └── emits telemetry ──▶ (consumed by control plane)│
                 └──────────────────────────────────────────────────────────────────────────┘
```

**Load-bearing invariant:** the **control surface is a hard interface.** The
router exposes its knobs; the tuner and orchestrator act *only through* those
knobs. This is what lets the router ship standalone and lets the control-plane
minds be developed, replaced, or run in a separate process without touching the
data path.

- **Data plane = the router (0001).** Fast, per-query, dumb. Runs unsupervised
  ("in the dark") with graceful degradation to static defaults. Useful out of the
  box. No hard dependency on the control plane.
- **Control plane = tuner (0002) + orchestrator (0003).** Out-of-band,
  asynchronous, never in the request path.
  - **Tuner** — *configuration/learning* function. Cross-session; recomputes
    router parameters from telemetry and hot-reloads them (no restart).
  - **Orchestrator** — *supervisory* function. Consumes **alarms** and performs
    **sampled volitional inspection**; can actuate policy overrides.

## 4. The router (data plane) — layers

1. **Prefilter (rules).** Cheap, deterministic. Sets `{class, floor, hint}`, can
   short-circuit obvious cases. Floors emotional at T1 (D5).
2. **Predictor (embed + kNN)** — *optional enrichment.* Proposes a starting tier.
   Currently P1-limited (see §8) → contributes *class*, not *tier*, at low n.
   Demoted from "the router" to "a class-prior that strengthens as n grows."
3. **Cascade (verify-and-escalate)** — **the spine.** Run a tier → apply a
   class/rung-appropriate verifier → escalate on fail. This is what makes the
   confidently-wrong small tier safe.
4. **Observability** — structured JSONL trace per query; PII-safe (hash, not
   content); the telemetry the control plane consumes.

**Cheapest-guess philosophy:** with no exemplars and no strong signal, the router
starts at the class's floor and lets the cascade escalate. A guess doesn't need to
be optimal — just cheap and better-than-random. No delusions about it being more.

## 5. Tier-suggestion taxonomy (prior art) — adopt / abandon / reconsider

"Suggesting a tier" splits by **what signal you use** and **when you look.**

### A. Predict before running — from the query alone
Cheap, but this is where **P1** bit us (query features show *class*, not difficulty).
- **Rules/heuristics** — length, keywords, code-fence/tool-list, task tags (LiteLLM, Redis-style gateways). Transparent, brittle.
- **Embedding + kNN** — route by nearest labeled neighbors (arXiv:2505.12601). Weak at low n / within-class difficulty.
- **Learned classifiers** — a "strong vs weak" head on preference data. **RouteLLM** ships BERT / matrix-factorization / causal-LLM routers (Chatbot-Arena + GPT-4-judge labels).
- **Difficulty / correctness predictors** — predict how hard a query is / whether the small model will succeed, route to the smallest predicted to succeed (arXiv:2511.03808; multi-task correctness heads). **The direct attack on P1.**

→ **ADOPT** rules + embedding-kNN as a *weak class-prior* (the blind router).
**ABANDON** any of these as the *primary* decision-maker (P1).
**RECONSIDER** the difficulty/correctness predictor **once n is large** (post-corpus) — the one method that attacks P1 head-on; likely a joint difficulty+quality multi-head (collapses predict+verify).

### B. Decide after running — from the output (deferral / cascade)
Sees the actual attempt; pays to run it. **This is our cascade.**
- **Confidence/uncertainty** — logprobs, entropy, self-consistency. Misses confidently-wrong-*consistent* errors (V-consistent).
- **Verifier/judge** — a checker or LLM-judge scores the answer; escalate on fail. **FrugalGPT** popularized the cost-saving cascade.
- **Self-assessment** — ask the model "can you solve this?"; escalate on decline (abstention).

→ **ADOPT as the spine.** All manifestations apply, chosen by certificate rung (§6). This is the core mechanism; the whole scheme lives or dies here.

### C. Learn the policy — adaptive
- **RL / bandit routers** — routing as sequential decision-making; learn cost-vs-reward from feedback. **Router-R1**; contextual bandits. Handles nonstationarity and the λ-tuning problem (K1) natively.

→ **DEFER to the tuner (0002).** This is control-plane territory. **RECONSIDER/adopt** as the tuner matures (bandit for λ, online policy).

### D. Route by preference/intent, not difficulty
- **Domain/action routing** — map query → domain/action → *preferred* model, regardless of difficulty. **Arch-Router-1.5B** is SOTA. Good when "best" is taste/policy, not correctness.
- **Orchestrator / multi-agent** — a controller LLM decides which expert(s) to invoke. **MasRouter**, mixture-of-agents, Composition of Experts.

→ **SPLIT.** The *orchestrator* idea → **ADOPT** as the control plane (0003), firm-based. *Preference/domain routing as our tier mechanism* → **ABANDON** (domain ≠ difficulty). **RECONSIDER** preference routing if we ever add taste/policy-based model choice on top of difficulty tiering.

## 6. The certificate-cost taxonomy (verifiers, cheapest first)

Organizing rule: **use the cheapest certificate that *reliably* catches the
class's failure, and it only pays if `certificate cost ≪ the escalation it
gates`.** Certificate cost has two axes — *compute* and *reliability*; cheap+
unreliable (rung 3) is the trap (false security).

| Rung | Certificate | Cost | Reliability | Example |
|---|---|---|---|---|
| **0 Structural** | parse/schema/grammar/type-check; no model/run | O(1) | deterministic *for structure*, blind to semantics | agentic nested-tool check |
| **1 Deterministic execution** | recompute / run tests / evaluate closed-form / ground-truth lookup | ms–s | **highest — a true certificate** | R2 plug-back; code→tests; fact→retrieval |
| **2 Self-signal** | logprob/entropy; self-consistency over k | k× cheap gen | medium; misses confident-systematic error | self-consistency pre-filter |
| **3 Learned lightweight judge** | small trained reward head / heuristic proxy | 1 small pass | **variable — the danger rung** | emotional listicle-ratio (leaky) |
| **4 LLM-as-judge** | verdict-only pass by a capable model | 1 short strong gen | good; ceilinged by judge competence | next-tier judge for non-checkable R1 |
| **5 No cheap certificate** | verify ≈ generate; only humans / peer model judge | ≈ gen cost | — | emotional attunement; creative; open investigation |

**Design rules:** cascade the certificate itself (rung 0→1→…); certificate rung
sets λ aggressiveness (cheap+reliable → aggressive; rung 3/5 → conservative or
fixed policy); **rung 5 means "don't verify — decide by fixed policy"** (why D5
floors emotional instead of verifying it); measure cost *relative to the
escalation it gates.*

## 7. The verifiability spine (why any of this works)

Determining difficulty ≈ doing the work — this is **no-free-lunch / P1**, not
solvable cheaply in general. The cascade escapes it by exploiting a **verify-vs-
solve asymmetry** (the P-vs-NP intuition — checking a certificate vs producing
one). It's an *analogy, not a theorem*, but the kernel is real:

- The **prediction** half hits the no-free-lunch wall (P1) — topic ≠ difficulty.
- The **verify** half is where the exploitable asymmetry lives. The cascade is
  efficient **exactly for the class of problems that admit a cheap certificate.**

**Consequence — organize classes by verifiability, not topic.** Code and math
carry cheap certificates (rung 1) → cascade is cheap and correct. Proofs, open
investigation, creative, emotional have no sub-linear certificate (rung 4–5) →
cascade breaks even or loses → fall back to a conservative fixed policy. This axis
cuts *across* any topic taxonomy and is the one that matters.

## 8. Empirical evidence base (don't re-derive)

From this session (harness `experiments/router/closure.py`; details in
`specs/0001/results.md`, `MODEL-EVAL-2026-07-15.md`):

- **P1 confirmed.** bge-small clusters queries by *class* (within 0.615 vs cross
  0.457, perfect NN by class) but **LOO tier accuracy 0.33 < 0.67 majority
  baseline** — every miss is same-class/different-tier. Embeddings see class, not
  difficulty.
- **Confidently-wrong small tier.** The 1.7B is fluent + structured + wrong on
  judgment tasks (R1 trap, A1 tool semantics). Forces the cascade.
- **Certificate asymmetry is per-class** (Exp 2, measured): agentic → rung-0
  nested-tool check catches it; checkable reasoning → rung-1 plug-back; emotional
  → rung-3 heuristic is *soft* (missed T0/E1 generic prose) → D5 floor.
- **λ directional:** global knee ~0.35; adopted per-class **0.40 / 0.35 / 0.20**
  (agentic/reasoning aggressive, emotional conservative via the verifier-
  reliability discount, D4).
- **~8B competence threshold** for emotional attunement; procedure is size-robust,
  insight is not.
- **Swap economics measured (Exp 4)** — the cascade survives its falsification
  test: model-swap ≈ 10 % of one T2 generation (T2 load ~3.8 s vs ~36 s of T2
  decode at 11 tok/s); T1→T2 break-even at ~30 % T1 success (measured ~67 %);
  **T0+T1 co-reside free** (2.93 GB, no throughput penalty); T0 is economically
  marginal except on prefilter-certain starts. `specs/0001/results.md` §Exp 4.

## 9. Decision & abandon register (with revisit triggers)

| Decision | Status | Revisit when |
|---|---|---|
| Router = dumb standalone data-plane; intelligence in the control plane | **adopted** | never (foundational) |
| Cascade (verify+escalate) as the routing spine | **adopted** | never |
| Embedder = bge-small (class-prior only) | **adopted** | V2 needs multilingual, or a difficulty feature lands |
| Per-class verifiers by certificate rung | **adopted** | new class added → assign its rung |
| Per-class λ from verifier-reliability principle | **adopted (directional)** | recalibrate on larger battery / via tuner |
| Heavy learned predictor as *primary* router | **abandoned** | n grows large → revisit difficulty/correctness multi-head |
| Class→tier as a clean map (topic ⇒ difficulty) | **abandoned** | never — topic ≠ difficulty (§7) |
| Per-token / per-phrase routing, latent bridging | **out of scope** | separate patchwork specs |
| Quorum/consensus governance | **out of scope** | it's a separate project |
| Co-resident tiers (assume 1 model resident) | **constraint** | RAM grows past ~24–32 GB |

## 10. Sequencing (the DAG)

```
Phase 0 (not yet spec'd): exemplar corpus + class-taxonomy expansion
        └─▶ re-run closure experiments (now meaningful, n ≫ 6)
                └─▶ 0001 predictor-posture decision
0001 data-plane router — buildable now for the dark core
   (prefilter + cascade + observability + CONTROL SURFACE)
        └─▶ control surface (hard interface) is prerequisite for:
                ├─▶ 0002 config-tuner            (plan next)
                └─▶ 0003 supervisory-orchestrator (plan next)
```

## 11. Settled vs. open

**Settled:** the plane split + control-surface-as-hard-interface; the design
tenet; cascade-as-spine; certificate-rung taxonomy; embedder (bge-small,
P1-limited); 3-class verifier config; observability schema; λ (directional);
governance (firm-based).

**Settled 2026-07-16:** control-surface schema **firmed**
(`specs/0001/control-surface.md` v1 — file transport + atomic rename, invariants
I1–I10, snapshot exemplar store); **cost model measured** (Exp 4: swap is
second-order, T0+T1 co-resident, T1→T2 is the paying edge); cascade policy +
cold-start defaults shipped as control-surface defaults.

**Open (router):** layer arbitration + who owns class detection (embedder is
better at class than rules — §8); infra-failure handling (tier down/OOM-thrash)
beyond the timeout basics; predictor posture (needs the corpus).

**Open (control plane, to plan next):** 0003 orchestrator **attention budget**
(recursive routing of its own inspection); 0002 tuner **trust/label-provenance**
on classes it can't cheaply label (inherits the certificate problem).

## 12. Cross-project pointers

- **Eval substrate:** `spark/MODEL-EVAL-2026-07-15.md` (capability matrix),
  `spark/bake-offs/` (27B vs Ornith), `spark/spikes/human-emotion-eval-skill.md`
  (the portable battery that seeds exemplars).
- **Harness + fixtures:** `patchwork/experiments/router/closure.py`.
- **Perf:** `patchwork/experiments/inference-bench/` result #003.
- **Models:** HF cache — Ornith-9B-4bit, Ternary-Bonsai 1.7B/8B/27B (all stock
  `mlx_lm`; 8B-1bit deleted, needed a fork).
- **Primary paper:** `specs/0001/references/2505.12601-*.pdf` (kNN ≥ learned).
- **Design rationale + failure modes:** `specs/0001/decisions.md`.

## 13. Glossary

- **n** — number of labeled exemplars in the kNN index (currently 6).
- **exemplar** — one stored `(query embedding → smallest tier that satisfied it)` datapoint; routing by precedent.
- **tier (T0/T1/T2)** — a served model by capability/cost. Here Bonsai 1.7B / 8B / 27B ternary.
- **certificate** — the check that an answer is good enough; its cost = the verify side of verify-vs-solve.
- **rung (0–5)** — certificate-cost band (§6).
- **P1** — the failure mode that embeddings encode class/topic, not difficulty; so pure-embedding tier prediction is weak.
- **control surface** — the router's exposed, machine-actuatable knobs; the hard interface between data and control planes.
- **data plane / control plane** — fast per-query path (router) vs. out-of-band async config/supervision (tuner + orchestrator).
- **alarm / volitional inspection** — reactive (certificate-backed) vs. proactive (sampled, for no-certificate classes) supervision — the two halves of the certificate ladder.
- **λ** — quality-vs-cost dial in `utility = quality − λ·cost`; per-class.
- **D#, V#, P#, K#, C#** — labeled decisions / verifier-limits / predictor-limits / calibration / cascade-economics entries in `specs/0001/decisions.md`.
