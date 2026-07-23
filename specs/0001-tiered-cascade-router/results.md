# Spec 0001 — Empirical closure results (2026-07-16)

The three empirical-closure experiments, run against the **n=6 battery**
(R1/R2/A1/A2/E1/E2 × the tier outputs captured this session). Harness +
fixtures: `experiments/router/closure.py` (run with the mlx-lm uv-tool python;
`bge-small-en-v1.5` from the HF cache).

> **Honesty header.** n=6 is the cold-start regime (failure mode P2). **Exp 2
> (verifiers) closes cleanly** — it tests real checks against real failure
> outputs. **Exp 1 & Exp 3 are directional.** Quality labels are the assistant's
> subjective judgments (rater n=1). Treat numbers as *decisions to adopt
> provisionally and recalibrate from observability data*, not final constants.

Labels (smallest tier that satisfies, quality ≥ 0.70): **R1→T1, R2→T0, A1→T1,
A2→T2, E1→T1, E2→T1**.

---

## Exp 1 — Embedder (bge-small): validated for its job; **confirms P1**

| Measure | Result |
|---|---|
| within- vs cross-class cosine | **0.615 vs 0.457** → class-locality HOLDS (+0.16) |
| nearest neighbours | R1↔R2, A1↔A2, E1↔E2 — perfect class clustering |
| LOO k=1 tier accuracy | **0.33 (2/6)**, *below* the 0.67 majority baseline |

The apparent contradiction is the finding: bge-small clusters flawlessly **by
class**, but all four misses are **same-class / different-tier** pairs (R1=T1 vs
R2=T0; A1=T1 vs A2=T2) — the embedder can't see **difficulty**. This is
failure-mode **P1**, demonstrated. The one correct pair (E1/E2) is the only pair
whose labels match.

**Decision:** keep `bge-small` — it does the coarse class-separation D2 assigned
it. But a *pure-embedding* kNN tier predictor is weak at low n. **V2 is
P1-limited, not embedder-limited.** Mitigations (design inputs, not blockers):
(a) add an explicit difficulty feature to the predictor, or (b) accept a
prefilter+cascade-dominant router early and let the exemplar-growth loop (D6)
strengthen the predictor as traffic accrues.

## Exp 2 — Verifiers: **closed**, with concrete config

Run against the real T0/T1 outputs in `fixtures/`.

| Class | Result | Decision |
|---|---|---|
| **Agentic** | nested-tool check flags **T0/A1** (3 nestings), passes **T1/A1** (0). Step-count heuristic false-positives T1 (11 legit steps). | **Adopt the nested-tool/semantics check; DROP step-sprawl.** |
| **Reasoning** | **T0/R1 flagged** (confidently-wrong "went to the clerk"), T1/R1 passes; R2 plug-back passes both (18/6 verified). | **Adopt** R2 ground-truth checker + R1 conclusion check. Passes V3 (safety). |
| **Emotional** | catches **T0/E2** (9-section listicle) but **MISSES T0/E1** (generic *prose*, 0 sections) and **over-flags T1/E2** (usable listicle). | Heuristic is **soft** → confirms V-emo. **Rely on the D5 floor (start emotional at T1), not the heuristic.** |

The load-bearing V3 catch (confidently-wrong T0 reasoning → escalate) **works**.
The emotional result is the important nuance: a cheap heuristic *cannot* reliably
catch T0's emotional failures (the E1 prose miss proves it), which is exactly why
D5 floors emotional at T1.

## Exp 3 — λ sweep: directional knee + per-class values

Global knee at **λ ≈ 0.3–0.5**: mean quality **0.88** at mean cost **0.37** (vs
0.99 / 0.85 at λ=0), **83% routed ≤ T1**. Past λ≈0.7, A2 wrongly drops to T1
(quality → 0.81) — the over-aggressive edge.

| Class | oracle λ range | binds because | **adopted λ** (D4-discounted) |
|---|---|---|---|
| reasoning | [0.25, 2.00] | wide — strong checker | **0.40** |
| agentic | **[0.25, 0.55]** | A2 needs T2 (binding) | **0.35** |
| emotional | [0.30, 2.00] | wide *by oracle only* | **0.20** ← weak verifier ⇒ conservative |

The oracle sweep alone doesn't force per-class λ (a global ~0.4 fits all three at
n=6). **Per-class λ is justified by D4** — emotional's wide oracle range is
untrustworthy because Exp 2 showed emotional can't be verified cheaply, so it's
discounted *down*. Principle over cost-curve.

---

## Exp 4 — Swap economics (2026-07-16): **the cascade survives its falsification test**

The open cost-model question (prd.md, architecture doc §11): on a 16 GB
single-resident box, escalation = *loading* a model — does swap latency eat the
cascade's savings? Harness: `experiments/router/swap_econ.py` (mlx-lm uv-tool
python); raw datapoints: `experiments/router/swap-econ.results.jsonl`.

**Measured (M2 16 GB, mlx_lm 0.31.3, 2 rounds, page-cache warmth uncontrolled):**

| Tier | load (r1/r2) | TTFT after load | decode tok/s | Metal peak |
|---|---|---|---|---|
| T0 1.7B | 0.77 / 0.70 s | 0.30 / 0.14 s | **127.1** | 0.61 GB |
| T1 8B | 1.39 / 1.21 s | 0.52 / 0.32 s | **36.7** | 2.43 GB |
| T2 27B | 4.24 / 3.44 s | 2.14 / 1.69 s | **11.0** | 7.86 GB |

Unload is free (~0.1 s). **Co-residency T0+T1 works:** both loaded = 2.93 GB
Metal peak, **zero throughput penalty** (T0 126.9, T1 36.7 tok/s — identical to
solo). The single-resident constraint is real only for T2.

**The verdict — generation dominates, swap is second-order.** For a ~400-token
answer: T0 ≈ 3.1 s, T1 ≈ 10.9 s, T2 ≈ 36.4 s of *generation*. The worst swap
(T2, ~3.8 s) is ~10 % of one T2 generation. The ternary 27B is so slow to decode
that the thing the cascade avoids (T2 generation) towers over the thing the
cascade costs (a wasted small attempt + a load).

**Break-even success rates** (expected-cost model, 400-tok answers, rung-0/1
verifier ≈ free):

| Transition | cascade beats direct-start when | battery says |
|---|---|---|
| T0→T1 (co-resident) | T0 success ≥ **28 %** | R2-class ✓; T0 satisfies 1/6 overall — *marginal, class-dependent* |
| T0→T1 (swap) | T0 success ≥ **31 %** | same |
| T1→T2 | T1 success ≥ **30 %** | T1 satisfies **4/6 ≈ 67 %** — *decisive win* |

**Design consequences (feed prd.md cost model + cascade policy):**
1. **The paying edge is T1→T2.** T1-start beats always-T2 by ~2.4× expected
   latency at the battery's T1 success rate. This is the cascade's economic core.
2. **T0 earns its place only on prefilter-certain mechanical queries** (its
   overall satisfy-rate ~17 % is *below* the 28 % break-even) — consistent with
   the class-start map (`agentic/reasoning → T0` only because rung-0/1 verifiers
   catch failures cheaply; emotional floors at T1 per D5).
3. **Keep T0+T1 co-resident by default** (2.9 GB total): a T0→T1 escalation then
   costs zero swap, which softens point 2.
4. **TTFT-after-escalation is the human-time cost:** a T1→T2 escalation shows
   ~12 s (T1 attempt) + ~3.8 s (load) + ~1.7 s (T2 TTFT) ≈ **17 s to first T2
   token**. Budget/interactivity policy should surface escalation to the caller
   (streaming a status line), not hide it.
5. RSS grew monotonically across the run (max 4.1 GB proc RSS) — watch for
   fragmentation on long-lived processes; the T2 OOM-thrash gotcha stands.

---

## Closure status

| Experiment | Status |
|---|---|
| Verifiers (Exp 2) | **Closed** — config decided (nested-check in, step-sprawl out; R1/R2 checks; emotional→D5 floor) |
| λ (Exp 3) | **Directional-closed** — global knee ~0.35; adopted per-class 0.40 / 0.35 / 0.20; recalibrate from traffic |
| Embedder (Exp 1) | **Informative** — bge-small kept; V2 is **P1-limited**; predictor needs a difficulty feature or exemplar growth |
| Swap economics (Exp 4) | **Closed** — cascade viable: swap ≈ 10 % of a T2 generation; T1→T2 edge wins ~2.4×; T0+T1 co-residency free; T0 restricted to prefilter-certain starts |

**Net effect on the design.** The centre of gravity shifts: at low exemplar
counts the kNN predictor contributes *class* but not *tier*, so the **prefilter +
cascade carry the routing** and the predictor strengthens over time via D6. This
is consistent with the design (the cascade was always the guarantee) but it
raises the priority of the difficulty-aware predictor rethink noted in
`decisions.md` (§closing) — the single most likely successor idea.

**State stays `draft`.** P1 is a design input, not a blocker; but before `ready`,
decide predictor posture (difficulty-feature vs prefilter/cascade-dominant) and
firm the λ values on a larger battery.

Reproduce: `uv run python experiments/router/closure.py`
