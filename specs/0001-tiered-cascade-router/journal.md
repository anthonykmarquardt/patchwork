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

## Episode 7 — The S4 decision: gate on intent, report the absolute (2026-07-17)

Operator ruled on the Episode-6 question: **option (b)**. S4 now gates on
*router overhead < 1% of the route's total cost* (worst measured 0.122%, E3);
the **20 ms absolute stays as the aspirational target** — verify.py prints
worst-case absolute overhead every run, non-gating, so drift stays visible.
Two operator constraints attached to the decision:

- **No black box.** The metric must be logged, not just benched. Confirmed
  already true: `overhead_ms` rides on `routing_decision` and
  `route_completed` telemetry and `router_overhead_ms` on every trace; the
  restated verifier line names the worst route and its absolute cost.
- **Native hardware where we can.** Surfaced a latent assumption: the
  embedder was thought to be mlx — it is **torch/transformers** (predictor.py
  loads bge-small via HF AutoModel on CPU; mlx runs only the generation
  tiers). That is *why* the 27B can evict it. The **mlx port of bge-small is
  now a planned backlog item** (CONTINUE.md #5): it removes torch from the
  query path, makes the eviction structurally impossible, and should beat the
  20 ms absolute for free — but it is a plan, not a gate.

Verifier re-run post-restatement: **all five thresholds PASS** →
`status.yaml` state flipped to **ready**. Spec 0001's empirical closure is
complete; 0002 (tuner) planning is unblocked and next.

## Episode 8 — The integration seams: the router meets its callers (2026-07-17)

Operator direction: refine the darkcore↔spark integration — all six named
seams, plus a spark-grade operator CLI with the gauge board live by default
on `serve`. Everything below was live-verified against real tiers.

**Two architecture decisions got made by the seams, worth recording:**

- **The context contract (seam 1).** Route and verify on the *last user
  message*; generate with the *full conversation*. Classification stays a
  single-utterance problem (the exemplar store and battery stay valid), while
  answers stop being amnesiac. First live test: T0✗→T1✗→T2✓ where the
  final answer honored both the system prompt and a name stated two turns
  earlier — with real usage (66 prompt / 317 completion) in the response.
- **Never stream unverified tokens (seam 4).** A cascade cannot stream what
  a verifier might still reject, so SSE sends escalation progress as comment
  lines (spec-compliant keep-alives that OpenAI SDKs ignore) and chunks the
  answer only after acceptance. The progress stream *is* the on_event
  channel from Episode 6, now caller-visible over HTTP.

**The rest:** route_id now returns to the caller (header + `patchwork`
object — the telemetry join key leaves the black box); usage is real (plus
total spend across attempts — the escalation tax, priced per response);
`/health?deep=1` exposes config/predictor/residency; endpoints went sync +
route-locked so health answers mid-climb (a supervised child that looks dead
during a T2 climb would get restart-looped). Spark now *owns* the router
(`spark darkcore-router` — spawn, health-wait, restart, reap; pure-TOML
runtime), with the relay demoted to remote-router duty.

**A bench-visible fix fell out:** the Bonsai-27B CoT-as-prose leak (bare
`</think>`, reasoning served as answer) is now stripped at extraction —
seam 1's first climb put the leak on screen in an API response, which is
what finally got it fixed. The 0002 poison-guard prerequisite (prd T2) is
half-done: served answers are clean; the admission-side detector remains.
