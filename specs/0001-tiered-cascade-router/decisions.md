# Spec 0001 — Design decisions & expected failure modes

> A living rationale document, in two parts. **Part 1** records *why* each choice
> was made. **Part 2** is an honest catalog of where the design is expected to
> fall short — the seams to watch and the openings for a different approach. Part
> 2 is written as an invitation, not a disclaimer: these are the places a new idea
> would earn its keep.

---

## Part 1 — Decision records

Each record: **Context → Decision → Rationale → Where it will fail / when to
revisit.**

### D1 — Three layers with a cascade spine, not a bare router
- **Context.** The T0 model (1.7B) is *confidently wrong* — fluent, structured,
  and incorrect on judgment tasks (measured: R1 trap, A1 tool semantics).
- **Decision.** Prefilter → kNN predictor → **cascade verify-and-escalate**. The
  predictor only chooses a *starting* tier; the cascade guarantees quality.
- **Rationale.** A pure upfront router that mispredicts emits a confidently-wrong
  answer with no recovery. The verify step is the only thing standing between a
  misprediction and a bad answer reaching the user.
- **Where it fails / revisit.** The cascade's guarantee is only as strong as the
  verifiers (see D3, and Part 2 §Verifier limits). If verification is weak for a
  class, the "guarantee" is illusory there.

### D2 — Embedder: `bge-small-en-v1.5` (default, pluggable)
- **Context.** Layer 2 needs to embed queries; candidates ranged from 33M
  (bge-small) to 0.6B (Qwen3-Embedding).
- **Decision.** `bge-small-en-v1.5`, L2-normalized, behind a plugin interface.
- **Rationale.** (a) arXiv:2505.12601 shows small embedders suffice for routing —
  bigger ones "barely help." (b) The 27B tier already sits at the 16 GB memory
  edge and thrashes if the box isn't clean; a 1.2 GB resident embedder eats exactly
  that headroom. (c) The embedder's real job is *coarse class separation*
  (emotional vs code vs math — easily separable), which bge-small does well.
  (d) Reversible via the plugin.
- **Where it fails / revisit.** Embeddings can't see *difficulty* (Part 2 §P1). If
  V2 accuracy is poor, or multilingual is needed, swap to Qwen3-Embedding-0.6B /
  bge-m3 — but that reopens the memory-headroom cost.

### D3 — Verifiers matched to each class's failure *type*
- **Context.** The cheapest verifier that catches the *observed* failure differs
  by class; a one-size verifier is either too weak or too expensive.
- **Decision.**
  - *Agentic* → **cheap structural check** (tool-call well-formedness; catches the
    observed `run_shell("http_get(...)")` nesting for free).
  - *Reasoning* → **ground-truth checker when checkable** (plug numbers back), else
    a **verdict-only next-tier judge** (~50 tokens), with self-consistency as an
    optional cheap pre-filter.
  - *Emotional* → **cheap heuristics** (listicle-ratio, interrogation count, cue-
    echo) **plus a prefilter floor at T1** so the verifier faces the subtler
    T1→T2 call, not gross T0 failures.
- **Rationale.** Match verifier *type* to failure *type*: structural failures get
  structural checks (near-free, strong); logical failures get checkers/judges;
  qualitative failures get heuristics + risk-avoidance (don't start at T0). Keeps
  every verifier ≪ escalation cost, or the cascade economics collapse.
- **Where it fails / revisit.** Structural checks pass *well-formed but bad* plans;
  judges inherit the judging tier's blind spots; emotional heuristics are gameable
  (Part 2 §Verifier limits). A learned per-class judge is the obvious next step if
  these prove too leaky.

### D4 — Per-class λ from a single principle
- **Context.** λ in `utility = quality − λ·cost` sets routing aggressiveness. One
  global λ or per-class?
- **Decision.** **Per-class**, derived from one rule: **`λ_class inversely tracks
  verifier reliability for that class`.** Strong/cheap verifier (agentic,
  checkable-reasoning) ⇒ high λ (aggressive, start low, lean on the cascade); weak
  verifier (emotional) ⇒ low λ (conservative, start high). Values chosen by a
  validation sweep at each class's Pareto knee, subject to the quality floor.
- **Rationale.** How aggressively you can route *down* depends on how reliably you
  can *catch* a down-misroute. This ties λ to D3 by a principle instead of three
  magic numbers, so the setting is defensible and re-derivable when verifiers change.
- **Where it fails / revisit.** λ is tuned on a tiny, non-representative battery and
  is static (Part 2 §Calibration). Real traffic will shift the knees; needs
  periodic recalibration from the observability data.

### D5 — Prefilter floors emotional at T1 (never gamble T0 on emotion)
- **Context.** Emotional quality is the least cheaply verifiable class; T0 fails it
  badly (generic listicle, missed cue).
- **Decision.** The prefilter detects the emotional class and sets a **floor of
  T1** — T0 is never the starting tier for emotional queries.
- **Rationale.** The cheapest way to make a class safe when you can't verify it well
  is to not gamble on the tier most likely to fail it. This shrinks the emotional
  verifier's job from "catch gross T0 failures" to "make the subtler T1→T2 call."
- **Where it fails / revisit.** Depends on correct *class* detection; a code
  question phrased emotionally, or vice-versa, defeats the floor (Part 2 §P-class).

### D6 — Observability-first; verified traces become exemplars
- **Context.** The router is a decision engine on constrained hardware with a small
  seed exemplar set; we must measure it to trust/tune/grow it.
- **Decision.** Structured JSONL per the repo Runtime Logging standard; a full
  per-request decision trace; an aggregate report; **hash-not-content** redaction
  per the PII rule; and an **exemplar-growth loop** (verified traces →
  feature-labeled exemplars appended to the kNN index).
- **Rationale.** (a) The empirical closure of D2/D3/D4 is *read off* this data —
  you cannot tune what you cannot see. (b) The kNN cold-start (Part 2 §P2) is
  mitigated by traffic densifying the index. Observability is thus both the
  measurement layer and part of the algorithm.
- **Where it fails / revisit.** PII-safe logging (hash, not text) limits root-cause
  analysis of qualitative failures — you see *that* an emotional answer was flagged
  but not *what* it said (Part 2 §Observability tension).

---

## Part 2 — Expected failure modes (where this design breaks)

Grouped by locus. Each: **symptom · why · blast radius · candidate rethink.**

### Predictor limits

- **P1 — Embeddings can't see difficulty.** *Symptom:* same-class, different-
  difficulty queries route to the same tier ("2+2" and a hard proof both embed as
  "math"). *Why:* embedders capture domain/register, not solve-difficulty. *Blast
  radius:* within-class the predictor adds little; the cascade does the real work,
  raising escalation rate. *Rethink:* add an explicit difficulty feature — a tiny
  difficulty classifier or prompt-difficulty prediction (arXiv:2511.03808) —
  concatenated to the embedding.

- **P2 — kNN cold-start on a tiny battery.** *Symptom:* near-random predictions at
  launch. *Why:* kNN with k≈100 needs hundreds of dense exemplars; the seed set is
  ~a dozen. *Blast radius:* the predictor is unreliable until traffic grows the
  index; early quality rests entirely on the prefilter + cascade. *Rethink:*
  synthetic exemplar generation to bootstrap density; or start prefilter-heavy and
  phase the predictor in as the index fills.

- **P-class — Class misdetection cascades.** *Symptom:* an emotionally-phrased code
  question gets the emotional floor + emotional verifier + emotional λ. *Why:* class
  detection is itself an error-prone routing problem. *Blast radius:* wrong verifier
  *and* wrong λ at once — a compounded miss at class boundaries. *Rethink:* treat
  class as a soft distribution, run multiple verifiers when class is uncertain.

### Verifier limits

- **V-struct — Structural check passes well-formed-but-bad.** *Symptom:* a
  syntactically valid but strategically dumb agentic plan is emitted. *Why:* the
  cheap agentic verifier checks *well-formedness*, not *quality*. *Blast radius:*
  agentic safety only covers "will it parse/run," not "is it a good diagnosis."
  *Rethink:* add a cheap plan-quality judge for agentic, accepting the cost.

- **V-consistent — Confidently-wrong-and-*consistent* reasoning slips through.**
  *Symptom:* a systematic reasoning bug reproduces across samples and passes self-
  consistency. *Why:* self-consistency only catches *random* errors. *Blast radius:*
  the exact confidently-wrong failure mode we're most worried about, when it's
  deterministic. *Rethink:* always back self-consistency with a judge for non-
  checkable reasoning; never rely on it alone.

- **V-judge — The judge inherits its tier's blind spots.** *Symptom:* T1 judging T0
  misses errors T1 would also make (correlated failure). *Why:* verifier quality is
  ceilinged by the judging tier. *Blast radius:* worst for emotional, where even
  T1/T2 are mediocre judges — the verifier is unreliable exactly where it's needed.
  *Rethink:* a *separately trained* discriminator (judging is often easier than
  generating), or human-labeled calibration for the hard classes.

- **V-emo — Emotional verification is fundamentally soft.** *Symptom:* generic-but-
  passable answers slip (false-accept); fine listicles get escalated (false-
  escalate). *Why:* no ground truth; heuristics are shallow and gameable. *Blast
  radius:* the T1→T2 emotional call stays noisy even with D5's floor. *Rethink:* a
  learned emotional-quality model, or accept a fixed T2-for-emotional policy and
  drop the pretense of verifying it.

### Cascade economics

- **C1 — Cost blowup on hard-heavy traffic.** *Symptom:* on a mostly-hard workload
  the router is *slower* than always-T2 — it pays T0→verify→T1→verify→T2. *Why:* the
  predictor can't see difficulty (P1), so it fails to send hard queries straight to
  T2. *Blast radius:* negative ROI exactly when the workload is demanding. *Rethink:*
  a predictor confidence threshold that skips straight to T2 — but that leans on
  prediction reliability, which P1/P2 undercut.

- **C2 — Verifier tax on every easy query.** *Symptom:* at high easy-query volume,
  a per-query judge pass becomes the bottleneck. *Why:* even when T0 is right, you
  pay to prove it. *Blast radius:* throughput ceiling on firehose workloads.
  *Rethink:* sample the verifier (verify a fraction), or gate the judge behind the
  cheap structural/heuristic check so most easy queries never reach it.

### Calibration & drift

- **K1 — Tuned on a tiny, unrepresentative battery.** *Symptom:* λ and verifier
  thresholds are over-fit to 6 prompts × classes; real traffic differs. *Why:* the
  seed data is a demo, not a distribution. *Blast radius:* miscalibration out of the
  gate. *Rethink:* treat launch calibration as provisional; recalibrate from
  observability data once real traffic accrues.

- **K2 — Model swap invalidates everything silently.** *Symptom:* swap a tier and
  the exemplar labels ("which tier passed") are now wrong, λ is stale, thresholds
  drift. *Why:* all calibration is relative to the current three models. *Blast
  radius:* any model change quietly degrades routing until full recalibration.
  *Rethink:* version the calibration to the model set; invalidate + re-seed on swap.

### Observability tension

- **O1 — PII-safe logging blunts root-cause analysis.** *Symptom:* an emotional
  answer is flagged, but the logs (hash + features, no text) don't show *what* it
  said. *Why:* the PII rule forbids logging raw content; qualitative debugging wants
  exactly that content. *Blast radius:* the hardest failures (emotional) are the
  hardest to diagnose from logs. *Rethink:* an opt-in, access-controlled, short-
  retention raw-capture channel for explicit debugging sessions — deliberately
  outside the default path, with consent.

---

### How to read this document
The cascade (D1) is the design's insurance policy, and Part 2 shows its premiums:
almost every failure mode traces back to two roots — **difficulty is hard to
predict (P1)** and **quality is hard to verify cheaply (V-*)**. A materially
different approach would attack one of those two directly (e.g. a trained
difficulty+quality multi-head model that does prediction *and* verification in one
pass, à la arXiv:2505.12601's multi-task variant), collapsing the predictor and
verifier into a single learned component. That is the most likely place a new idea
supersedes this one.
