# dark-core v0 / v0.1 — benchmark findings report

> **Runs:** 2026-07-16, M2 16 GB, mlx_lm 0.31.3, config v2. 12 queries
> (6 labeled + 6 probes) through the real cascade, plus a T2-only baseline on
> the labeled 6. **v0** = shipped verifiers (report-v0.json); **v0.1** = v0 +
> the rung-0 tool-semantics layer (rec #1 below), baselines reused
> (report.json). **Reproduce:** `$MLXPY experiments/router/darkcore_bench.py
> [--label ... --skip-baseline report-v0.json]`; thresholds:
> `python3 experiments/router/verify.py --assert-thresholds`. Telemetry:
> `logs/router/2026-07-16.jsonl` (view: `$MLXPY -m darkcore.tui --replay`).

## v0.1 re-bench — the S1 fix, verified. ALL THRESHOLDS PASS.

One variable changed: `nested_tool_check` gained an **argument-shape table**
(url/path/host classes, call- and command-syntax parsing — still rung 0,
deterministic, model-free).

| | v0 | v0.1 |
|---|---|---|
| S1 mean quality (labeled) | 0.792 **FAIL** | **0.900 PASS** |
| speedup vs T2-only | 1.66× | **1.72×** |
| ≤T1 routing | 83.3% | 83.3% |
| escalation rate | 0.333 | 0.417 |
| A1 path | T0✓ *(false-accept)* | **T0✗ → T1✓** (29.6 s) |

What it proves: the v0 A1 failure is **deterministic, not sampling luck** —
T0 re-emitted `http_get /etc/nginx/nginx.conf` and the shape check flagged it
live (`shape_detail: ["http_get given filesystem path"]`), escalating to T1
(label 0.85). Quality rose 0.108 while total cascade time *fell* (one T0→T1
climb costs ~24 s; co-residency makes it swap-free). The escalation-rate rise
is the mechanism working, not a regression. E3's P-class miss reproduced
untouched (deliberately out of scope — that's rec #2, the embedder).

---

## Verdict, one paragraph

The cascade works as designed and pays for itself: **1.66× faster than
T2-only** on the labeled battery while routing **83% of queries at or below
T1**, with the load-bearing safety property intact (the confidently-wrong T0
answer to R1 was caught twice and escalated to T2). The economics inverted
our fears: **model-swap cost is 0.5% of total spend** (Exp 4's co-residency
policy erased it) while the **rung-4 judge tax is 26%** — the real cost
center is verification, not swapping. The bench **fails one spec threshold
(S1 quality retention: 0.792 vs 0.992, ε 0.15)**, and the failure is
maximally instructive: a single rung-0 false-accept (A1) — the V-struct seam
predicted in decisions.md — accounts for the entire gap. Every failure mode
that surfaced was one Part 2 of decisions.md already named.

## Spec thresholds (verify.py)

| # | Criterion | Result | Detail |
|---|---|---|---|
| S1 | quality retention (≥ T2-only − 0.15) | **FAIL** | 0.792 vs 0.992 — entirely A1's rung-0 false-accept (label 0.20) |
| S2 | safety: R1 escapes T0 | **PASS** | T0✗ → T1✗ → T2, 2 escalations |
| S3 | ≥60% labeled at T0/T1 | **PASS** | 4/6 (67%) |
| S4 | router overhead < 20 ms | **PASS** | max **0.05 ms** (~400× under budget) |
| S5 | observability complete | **PASS** | all 12 routes reconstruct path+latency from logs alone |

## Per-route results

| id | class (detected) | path | wall | note |
|---|---|---|---|---|
| R1 | reasoning | T0✗→T1✗→T2✓ | 259.7 s | **the safety catch** — judge rejected both small tiers |
| R2 | reasoning | T0✓ | 5.3 s | rung-1 certificate; 37× cheaper than T2-only (198.6 s) |
| A1 | agentic | T0✓ | 6.0 s | **V-struct false-accept** — well-formed, semantically absurd (`http_get` on a file path) |
| A2 | default *(miss: agentic)* | T0✗→T1✗→T2✓ | 332.8 s | judge chain landed the labeled-correct tier (T2) |
| E1 | emotional | T1✓ | 7.5 s | D5 floor; 15× cheaper than T2-only (117.0 s) |
| E2 | emotional | T1✓ | 27.4 s | D5 floor |
| R3 | reasoning | T0✓ | 2.8 s | the dream path: rung-1, under 3 s |
| R4 | reasoning | T0✓ | 8.8 s | T0 *genuinely solved* the bat-and-ball trap ($0.05); judge pass legit |
| A3 | agentic | T0✓ | 5.1 s | rung-0 pass, plan plausible |
| A4 | agentic | T0✓ | 5.3 s | **V-struct again** — ordered calls, weak strategy (never isolates the AZ) |
| E3 | default *(miss: emotional)* | T0✓ | 9.4 s | **P-class miss → V-judge false-accept** (see below) |
| E4 | emotional | T1✓ | 29.3 s | D5 floor (caught by "I just feel …") |

Aggregate: tier distribution **T0×7 / T1×3 / T2×2**; escalation rate 0.33;
class detection 10/12; zero flags, zero alarms, zero infra failovers.

## The economics (measured, labeled subset)

| | cascade | T2-only |
|---|---|---|
| total wall | **638.7 s** | 1061.5 s |
| mean quality (session labels) | 0.792 | 0.992 |

**Cost decomposition across all routes: swap 0.5% · generation 73.2% ·
verification 26.2%.**

- **Exp 4's swap fear is dead.** T0+T1 co-residency plus only two T2 climbs
  → 3.8 s of loading against ~700 s of everything else.
- **The judge is the new cost center (C2 confirmed).** Every rung-4 verify is
  a short next-tier generation — and on the escalation path it runs at *each*
  rung. R1/A2 each cost ~1.4–1.8× a direct T2 run (C1 premium on hard
  queries: 259.7 vs 179.3 s; 332.8 vs 188.7 s).
- **The fleet of cheap wins buys the climbs back.** Eight routes finished in
  2.8–9.4 s each; T2-only averages ~177 s/query because the thinking model
  burns its token budget on *everything*. Net: 1.66× on a battery that is
  deliberately hard-heavy (2 of 6 labeled queries need T2). Easy-heavy real
  traffic would widen this; an all-hard workload would invert it (C1).

## The instructive failures (all predicted in decisions.md Part 2)

1. **V-struct is the S1 gap — rung-0 passes well-formed-but-bad (A1, A4).**
   The nested-tool check catches the *fixture's* failure signature but this
   run's T0 emitted structurally clean calls with absurd semantics
   (`http_get /etc/nginx/nginx.conf`) and strategically weak plans. Rung 0
   alone under-verifies the agentic class. *Candidate fixes:* a cheap
   tool-semantics table (which tool accepts what argument shape — still rung
   0), or a rung-4 judge sampled behind the structural check.
   *Caveat:* quality scores reuse the session's fixture labels; this run's
   A1 answer differs from the fixture (sampling), so 0.792 is an estimate —
   but the answer is visibly weak (`bench-answers/A1.txt`).
2. **P-class miss cascades (E3).** "…that makes me furious" missed the
   affective lexicon → class `default` → no D5 floor → T0's generic
   self-audit listicle ("What were your weaknesses?" to someone raging at
   platitudes) → **T1 judge passed it** (V-judge: a mediocre judge can't
   certify attunement). One lexicon gap defeated three defenses in a row.
   *This is the strongest argument yet for moving class detection to the
   embedder* (Exp 1: class-locality is the one thing embeddings are good at,
   even at n=6).
3. **A2 class-missed but tier-landed.** The judge chain is a robust (if
   expensive) backstop when class detection fails toward `default` — the
   rung-4 default is conservative in the right direction. Failing toward
   `default` is safe; failing toward a *wrong specific class* (E3) is not.
4. **Bonsai-27B leaks narrated CoT.** No `<think>` tags — it writes "Here's
   a thinking process:" as prose, so answers from T2 open with reasoning
   narration (R1). Answer extraction needs a per-model output profile.
   Cosmetic here, but it would poison exemplar labels downstream (0002).

## What this run does NOT establish

- Quality numbers are session labels (rater n=1) reused across a fresh
  sampling run — directional, not calibrated.
- n=12 with 3 classes; no multilingual, no code-gen, no world-fact.
- Escalation-rate/λ interactions untested (λ is currently unused — the
  predictor is off; start tiers come from the class map).
- Single-process, sequential. No concurrency, no OOM-thrash reproduction.

## Recommended next actions (priority order)

1. ~~**Agentic verifier: add a semantics layer to rung 0**~~ — **DONE (v0.1):
   S1 passes** (0.900 vs 0.842 threshold). See the v0.1 section up top.
2. **Class detection → embedder.** Prefilter keeps floors/short-circuits;
   bge-small class-prior owns class (Exp 1 supports; E3 is the proof of
   need). This is the "layer arbitration" open item — resolve it in favor of
   the embedder.
3. **Judge economics:** exercise `skip_start` for judge-chain classes (an
   A2-shaped query that starts at `default` should climb once, not twice) and
   cap judge token budget by tier.
4. **Escalation UX:** surface escalations to the caller as a status stream —
   17–25 s to first token on a climb is fine *if visible*, hostile if silent.
5. Feed all of this to **0002 (tuner)** planning — every recommendation above
   is a control-surface patch a tuner could learn, which is the point of the
   architecture.
