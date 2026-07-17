# Spec 0001 — Journal: how we got here, and why the next steps are what they are

> **Purpose.** The narrative record of the build — the chain from *evidence* to
> *decision* to *next step*, so a future session (or mind) can see not just
> WHAT was decided but WHY, and would re-derive the same priorities from the
> same facts. Companion to `decisions.md` (design rationale) and `results.md`
> (numbers). Append new episodes; don't rewrite history.

---

## Episode 1 — Design on paper (2026-07-15 → 16 early)

Eval work in spark established the three tiers and THE shaping fact: **the
1.7B is confidently wrong** — fluent, structured, incorrect on judgment. That
killed the "pure predictor" router (a misprediction ships a bad answer with no
net) and forced the **cascade**: run cheap → *check* → escalate on fail.

Closure experiments added the second shaping fact, **P1**: embeddings cluster
queries by *kind* (class) but are blind to *difficulty* — LOO tier prediction
0.33 vs 0.67 baseline. So the "smart upfront guess" was demoted to a class
hint, and the checking layer became the load-bearing part. Verifiers were
organized by **certificate cost** (how cheap and how reliable is the check):
plug-the-number-back is near-free and proof-grade; "judge it" costs a model
call; emotional quality has *no* cheap check — so don't check it, just never
start it on the small model (the D5 floor).

The architecture then split into a **dumb, standalone router** (data plane)
and future **smart tuners/supervisors** (control plane) that may only act
through a **control surface** — explicit, bounded, versioned knobs. Rationale:
for problems with no closed-form answer (difficulty, quality), don't freeze a
guess into the tool; expose valves and let an intelligent operator tune them.

## Episode 2 — Falsify before building (2026-07-16, Fable session)

Before writing the router we attacked the design's cheapest kill-shot: on a
16 GB single-resident box, **escalation = loading a model**. If swaps were
expensive, the cascade dies. Measured (`swap_econ.py`, results.md §Exp 4):

- swap ≈ 10% of ONE big-model generation → generation dominates, swap is noise;
- T0+T1 fit in RAM together with zero speed penalty → small escalations are free;
- T1→T2 escalation pays for itself if T1 succeeds ≥30% (measured ~67%).

**Decision unlocked:** build it. Also fixed the residency policy (keep small
tiers co-resident; only the 27B gets the box alone) — measured, not assumed.

## Episode 3 — Build the dark core (same day)

`darkcore/`: prefilter → cascade → telemetry, with the **control surface
firmed and implemented first-class** (versioned config file, invariants
I1–I10, atomic swap, audit journal). The predictor stayed OFF (P1 + no
exemplar corpus yet). Every route emits a full decision trace, PII-safe
(hashes and features, never content) — the telemetry is both the debugging
substrate and the control plane's future food. The **gauge board** TUI renders
it for the operator.

## Episode 4 — Bench v0: two predicted seams show up with receipts

12 queries through the real cascade + an always-27B baseline. Wins: 1.66×
faster, 83% of routes never touch the 27B, the confidently-wrong trap was
caught twice and correctly landed on T2, router overhead 0.05 ms. Cost
decomposition surprised us in a *good-then-bad* way: **swap 0.5%** (fear
dead), **judge tax 26%** (fear we hadn't priced).

Failures — both **predicted in decisions.md Part 2 before any code existed**:

- **V-struct (A1):** the structural checker passed a well-formed-but-absurd
  plan (`http_get` fed a filesystem path). Grammar ≠ sense. This single
  false-accept was the entire S1 quality-threshold failure.
- **P-class (E3):** "…makes me furious" missed the affective keyword list →
  never classified emotional → no T1 floor → small model emitted a tone-deaf
  listicle → the T1 judge passed it (a mediocre judge can't grade empathy).
  One keyword gap defeated three defenses in a row.

## Episode 5 — One-variable fix, re-bench (v0.1)

Method note: change ONE thing, hold baselines, re-run. The rung-0 checker
gained an **argument-shape table** (this tool takes URLs, that one takes
paths; parse both `tool(arg)` and `tool arg` syntax). Result: T0 re-emitted
the *same* absurd call (deterministic failure, not sampling luck), the check
caught it live, A1 escalated to the correct tier. **Quality 0.792 → 0.900,
speedup 1.66× → 1.72×, all five spec thresholds pass.** E3 reproduced
untouched — deliberately out of scope for the one-variable run.

## How the next steps were derived (the actual logic)

Each recommendation is the cheapest attack on a *measured* fact:

| Evidence (measured) | Inference | Next step |
|---|---|---|
| E3: keyword classing missed an emotional query and the miss cascaded; Exp 1: embeddings separate *class* nearly perfectly even at n=6 | class detection is the brittle link, and we already own a tool that's good at exactly this | **(1) embedder-owned class detection** (prefilter keeps floors/short-circuits) |
| judge calls = 26% of all spend; A2 paid two full climbs (332 s) vs 189 s direct; ambiguous queries default into the judge-chain path | ambiguous queries shouldn't start at the bottom of the ladder; judges shouldn't get unbounded token budgets | **(2) skip-start for low-confidence classes + judge token caps** |
| a T1→T2 climb ≈ 17–25 s to first token; R1/A2 ran 4–5 min with zero caller feedback | latency is acceptable only when visible | **(3) stream escalation status to the caller** |
| every fix in this journal was applied as a config/knob change (journaled patches); the surface is proven live | the tuner (0002) has a real, tested actuation path — its planning is unblocked and its job list is literally the rows above | **(4) plan the control plane** |
| every quality number here rests on n=6 labels, rater n=1; P1/P2 say the predictor stays weak until n grows | nothing calibrates without a corpus | **(5) exemplar corpus (Phase 0)** |

The meta-method, for reuse: **predict failure modes in writing → build the
falsifier first → bench → match observed failures to predictions → fix the
cheapest confirmed seam, one variable at a time → re-bench → let the surviving
failures rank the backlog.** The backlog above wasn't chosen; it fell out.

## Episode 6 — Steps 1–3 shipped; bench v0.2 (2026-07-17)

**Built:** the class-prior predictor (bge-small kNN over an immutable
21-exemplar snapshot, **published through the control surface** — config v3,
journaled — exactly the tuner's future write path, exercised by hand);
arbitration pinned (deterministic rules win when they fire → embedder owns
the rest → low confidence abstains); judge token caps + skip-start; live
escalation status to the caller.

**Two design moments worth remembering:**
- *Correct classification can lower quality.* Classing A2 correctly (agentic)
  would have handed its checklist answers to a rung-0 check with nothing to
  check — a vacuous pass at T0. Resolution came from the architecture itself:
  **a certificate that has nothing to certify is inconclusive, not a pass** —
  rung 0 falls through to the rung-4 judge (§6 "cascade the certificate").
- *The 27B evicts the embedder.* First classify after a T2 climb paid
  24→197 ms (page-fault reload of torch weights; run-to-run variance is pure
  page-cache luck). Fix: **the route that loads the exclusive tier re-warms
  the embedder at its own tail** — costs land on their cause, never the next
  query. Single-resident hardware keeps teaching the same lesson: residency,
  not compute, is the scarce resource.

**Bench v0.2 (three-run table in BENCH-REPORT.md):** class detection 12/12
(E3 fixed with a receipt — the answer engages the stated cue); quality 0.900
held; **1.90× vs T2-only**; judge tax 26.2% → 24.5%; safety catch stable
across all three benches. **S4 fails by 2.36 ms** (22.36 vs 20 ms, worst
route, paging residue) — iteration stopped deliberately; the budget's
*intent* (overhead ≪ generation) is honored at 0.008% of the route that
carries it. **Operator decision requested:** absolute 20 ms (→ pin or port
the embedder) vs restate as <1% of route cost.

**Next steps as derived now:** (a) the S4 budget decision (operator); (b) plan
0002 tuner — the seed script literally performed the tuner's job by hand this
episode, so its spec can be written from a working example; (c) 0003
orchestrator (attention budget); (d) Phase-0 corpus (unchanged); (e) residual
known-blindness: rung-0 passes valid-but-strategically-weak agentic plans
(A4) — attack via sampled judge or the tuner's exemplar growth, not more
rung-0 rules.
