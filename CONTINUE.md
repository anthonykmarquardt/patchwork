# Patchwork — CONTINUE.md

> **Handoff snapshot.** Read this first when resuming work in a new session.
> **Rule:** Overwrite at end of session. Never append. This is a snapshot, not a history.

---

## Bootstrap Sequence (Do This First, In Order)

```bash
cd ../patchwork
git status && git log --oneline -5      # expect dark-core v0.2 commits at HEAD, clean tree

# THE conceptual entry point:
cat docs/routing-architecture.md

# The JOURNEY — evidence→decision→next-step chain, episodes 1–6 (read 2nd):
cat specs/0001-tiered-cascade-router/journal.md

# The bench findings (v0 → v0.1 → v0.2 comparison up top):
cat experiments/router/BENCH-REPORT.md

# Watch it happen on the gauge board (~2 min):
MLXPY=$HOME/.local/share/uv/tools/mlx-lm/bin/python
cd experiments/router && $MLXPY -m darkcore.tui --replay --speed 30
```

---

## Current Status (2026-07-17)

**dark-core v0.2: built, benched three times, steps 1–3 of the backlog done.**

- **Predictor live in class-prior mode** (`darkcore/predictor.py`): bge-small
  kNN over an immutable exemplar snapshot (n=21), published through the
  control surface (config **v3**, journaled). Class detection **12/12**;
  the E3 emotional miss is fixed with a receipt. Arbitration pinned:
  rules-when-they-fire > embedder > abstain-to-default.
- **Rung-0 verifier** now: nesting + arg-shape + **inconclusive→judge
  fallthrough** (a certificate with nothing to certify is not a pass).
- **Judge caps** (T1 256 / T2 512 tokens) + **skip_start** for unclassifiable
  queries; judge tax 26.2% → 24.5%.
- **Escalation visibility**: `route(query, on_event=...)`; CLI streams
  `◉ ✓ ✗ ➜` status on stderr.
- **Bench v0.2 final:** quality 0.900 (S1 ✓), safety stable ×3 (S2 ✓),
  83% ≤T1 (S3 ✓), observability ✓, **S4 ✓ as restated** (<1% of route cost,
  worst 0.122%; 20 ms absolute kept as aspirational target — see decision
  below). **All 5 thresholds pass.**

## S4 DECISION — RESOLVED 2026-07-17: option (b). Spec 0001 is READY.

Operator chose **(b)**: S4 gates on *overhead < 1% of route cost* per route
(worst measured 0.122%). The **20 ms absolute stays as the aspirational
target** — verify.py reports worst-case absolute overhead every run
(non-gating), and overhead remains fully observable per route (`overhead_ms`
on `routing_decision`/`route_completed` events, `router_overhead_ms` in every
trace) — no black box. Verifier run post-change: **all 5 thresholds PASS**;
`status.yaml` flipped to `ready`. Corollary decisions: the embedder is
**torch/transformers, not mlx** (predictor.py loads bge-small via HF
AutoModel — the mlx side is only T0/T1/T2 generation); **mlx port of
bge-small is now a planned backlog item** (native hardware; makes the 27B
eviction structurally impossible), not an S4 gate.

## Router Server & Integration (NEW)

The **dark-core router now runs as a standalone OpenAI-compatible inference
server** (`darkcore.server`). Agent harnesses can call it directly, or via spark
(which relays). The server manages T0/T1/T2 lifecycle internally — no external
config needed for basic operation.

**Quick start:**
```bash
cd experiments/router
# Terminal 1: start the router server
$MLXPY -m darkcore.server --port 8000

# Terminal 2: test it (agent harness style)
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "patchwork-dynamic-router",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }' | python3 -m json.tool
```

**With spark (via relay):**
- Spark v2 (spark repo) now has a `relay` backend type
- Configure: `config/runtimes/relay.toml` → `relay_base_url = "http://localhost:8000"`
- Then: `spark <model-configured-as-relay>` → proxies to the router transparently
- Agent harness calls spark normally; spark handles relay under the hood

**Integration:** The router is completely decoupled from spark. The relay is a
generic proxying layer (useful for any external OpenAI-compatible service). This
lets the router develop independently in patchwork while spark eventually absorbs
it as a first-class citizen.

## What's Next (Prioritized)

> Derivations: journal.md Episode 6 tail. Bench snapshots:
> report-v0 / v0.1 / v0.2-rc1 / v0.2-rc2 / report.json (final).

1. ~~S4 budget decision~~ — DONE 2026-07-17 (option (b), above); spec 0001
   is `ready`, all thresholds pass.
2. ~~Plan 0002 (tuner)~~ — PLANNED 2026-07-17: full prd.md + design.md in
   specs/0002-config-tuner/. Core: provenance ladder (L0 certificates
   auto-admit / L1 judge quarantined+corroborated / L2 rung-5 refused);
   class vs tier labels admitted separately; propose-then-apply CLI.
   **Needs operator sign-off on 4 open items (prd.md tail)** — then
   implement (T1 candidate buffer first; it gates the growth loop).
3. **Plan 0003 (orchestrator).** Hard core: the attention budget. Alarm feed
   exists (`terminal_failure`, `budget_exhausted`); silent-failure sampling
   does not yet.
4. **Phase-0 exemplar corpus** (n ≫ 21) → tier prediction posture → recalibrate
   λ (still unused: predictor abstains from tiers at low n).
5. **mlx port of the bge-small embedder** (planned, per operator: use native
   hardware where we can). Today it's torch/transformers on CPU
   (predictor.py); an mlx-resident embedder removes the torch dependency from
   the query path and ends the 27B-eviction/rewarm saga structurally — and
   should comfortably beat the 20 ms aspirational absolute target.
   **Sequencing pressure discovered while planning 0002 (D4):** production
   exemplars store embeddings, never text (PII) — an embedder migration
   invalidates them all with no re-embed path. **Port while n is small**
   (before the growth loop ships), or pay a corpus reset.
6. Residual seams (attack via tuner, not more rules): rung-0 blind to strategy
   (A4); Bonsai-27B CoT-as-prose leaks into answers (would poison exemplar
   labels — fix answer extraction before the growth loop ships).

## Gotchas

- Run darkcore/TUI **from `experiments/router/`** with the mlx-lm uv-tool
  python (`$MLXPY`). Config is at **v3** (predictor on, skip_start on).
- Re-seeding exemplars: `seed_exemplars.py` bumps the snapshot version — it
  will `conflict` if config moved; read current version first (by design).
- **The 27B evicts the embedder** (the S4 saga) — any new resident component
  must assume T2 wipes the page cache; put rewarms at the evicting route's
  tail, and never trust solo latency measurements on this box.
- T0+T1 co-reside safely; only T2 needs the box alone (Exp 4).
- Thinking-tier T2: ≥1000 completion tokens or empty answers; narrates CoT
  without `<think>` tags.
- Bench answer snapshots: `experiments/router/bench-answers/` (bench artifact,
  not logs; telemetry stays hash+features per the PII rule).
- Eval substrate lives in **spark**: `spark/MODEL-EVAL-2026-07-15.md`.
